import json
import random
import logging
import zlib
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, Any
from app.config import DATABASE_PATH
from app.core.models import (
    Transaction, AIDiagnosisResult, RuleValidationResult,
    ExecutionResult, AuditLog, TransactionStatus, DeclineCategory,
    FailureReason, RecoveryActionType, quantize_currency, get_utc_now_iso
)
from app.core.database import update_transaction_status, insert_audit_logs

logger = logging.getLogger(__name__)


def _to_enum_val(val: Any) -> str:
    """Safely extracts raw string enum value regardless of enum instance or string type."""
    if hasattr(val, "value"):
        return str(val.value).upper()
    return str(val).upper()


def simulate_recovery_attempt(
    transaction: Transaction,
    action: RecoveryActionType,
    discount_pct: float = 0.0,
    seed_val: Optional[int] = None
) -> ExecutionResult:
    """
    Deterministic mock payment gateway / recovery simulator.
    Evaluates recovery actions deterministically based on transaction metadata.

    Reproducible outcomes for test and hackathon demonstration.
    """
    if seed_val is None:
        seed_str = f"{transaction.transaction_id}_{transaction.attempt_count}_{action}"
        seed_val = zlib.crc32(seed_str.encode("utf-8")) % (2**31)

    rng = random.Random(seed_val)
    reason = _to_enum_val(transaction.failure_reason)
    category = _to_enum_val(transaction.decline_category)
    action_type = _to_enum_val(action)

    # 1. Action Blocked or No Action
    if action_type == RecoveryActionType.NO_ACTION_BLOCK.value:
        return ExecutionResult(
            transaction_id=transaction.transaction_id,
            action=RecoveryActionType.NO_ACTION_BLOCK,
            execution_status="BLOCKED",
            success=False,
            recovered_amount=Decimal("0.00"),
            gateway_response_code="BLOCK_RULE_ENGINE",
            execution_time_ms=10,
            message="Recovery action blocked by merchant safety rule engine."
        )

    # 2. Manual Review
    if action_type == RecoveryActionType.MANUAL_REVIEW.value:
        return ExecutionResult(
            transaction_id=transaction.transaction_id,
            action=RecoveryActionType.MANUAL_REVIEW,
            execution_status="MANUAL_REVIEW",
            success=False,
            recovered_amount=Decimal("0.00"),
            gateway_response_code="PENDING_HUMAN_REVIEW",
            execution_time_ms=15,
            message="Transaction flagged for manual merchant review. No payment attempt executed."
        )

    # 3. Hard Declines (Fraud / Closed Account)
    if (
        category == DeclineCategory.HARD_DECLINE.value
        or reason in [FailureReason.FRAUD_STOLEN_CARD.value, FailureReason.ACCOUNT_CLOSED.value]
    ):
        return ExecutionResult(
            transaction_id=transaction.transaction_id,
            action=action,
            execution_status="HARD_FAILED",
            success=False,
            recovered_amount=Decimal("0.00"),
            gateway_response_code="ERR_PERMANENT_DECLINE",
            execution_time_ms=85,
            message=f"Gateway rejection: Permanent hard decline ({reason})."
        )

    # 4. Data Mismatches (Expired Card / Authentication Failure)
    if reason in [FailureReason.EXPIRED_CARD.value, FailureReason.AUTHENTICATION_FAILURE.value]:
        if action_type in [RecoveryActionType.PAYMENT_LINK_SMS.value, RecoveryActionType.DUNNING_EMAIL.value]:
            return ExecutionResult(
                transaction_id=transaction.transaction_id,
                action=action,
                execution_status="COMMUNICATION_SENT",
                success=False,
                recovered_amount=Decimal("0.00"),
                gateway_response_code="NOTIF_SENT_200",
                execution_time_ms=140,
                message=f"Outreach communication ({action}) dispatched to customer. Awaiting payment method update."
            )
        else:
            return ExecutionResult(
                transaction_id=transaction.transaction_id,
                action=action,
                execution_status="SOFT_FAILED",
                success=False,
                recovered_amount=Decimal("0.00"),
                gateway_response_code="ERR_EXPIRED_CARD",
                execution_time_ms=90,
                message="Direct payment retry failed: Card is expired."
            )

    # 5. Soft Declines: Insufficient Funds
    if reason == FailureReason.INSUFFICIENT_FUNDS.value:
        if action_type in [RecoveryActionType.SMART_RETRY.value, RecoveryActionType.INCENTIVIZED_RETRY.value]:
            is_success = rng.random() < 0.70
            if is_success:
                if action_type == RecoveryActionType.INCENTIVIZED_RETRY.value and discount_pct > 0:
                    multiplier = Decimal(str(1.0 - (discount_pct / 100.0)))
                    rec_amount = quantize_currency(transaction.amount * multiplier)
                else:
                    rec_amount = transaction.amount

                return ExecutionResult(
                    transaction_id=transaction.transaction_id,
                    action=action,
                    execution_status="RECOVERED",
                    success=True,
                    recovered_amount=rec_amount,
                    gateway_response_code="200_SUCCESS",
                    execution_time_ms=210,
                    message=f"Payment successfully recovered via {action}! Recovered: ${rec_amount}."
                )
            else:
                return ExecutionResult(
                    transaction_id=transaction.transaction_id,
                    action=action,
                    execution_status="SOFT_FAILED",
                    success=False,
                    recovered_amount=Decimal("0.00"),
                    gateway_response_code="ERR_INSUFFICIENT_FUNDS",
                    execution_time_ms=180,
                    message="Gateway soft decline: Insufficient funds."
                )
        else:
            return ExecutionResult(
                transaction_id=transaction.transaction_id,
                action=action,
                execution_status="COMMUNICATION_SENT",
                success=False,
                recovered_amount=Decimal("0.00"),
                gateway_response_code="NOTIF_SENT_200",
                execution_time_ms=130,
                message=f"Dunning communication ({action}) sent to customer."
            )

    # 6. Soft Declines: Temporary Bank Failure
    if reason == FailureReason.TEMPORARY_BANK_FAILURE.value:
        is_success = rng.random() < 0.85
        if is_success:
            return ExecutionResult(
                transaction_id=transaction.transaction_id,
                action=action,
                execution_status="RECOVERED",
                success=True,
                recovered_amount=transaction.amount,
                gateway_response_code="200_SUCCESS",
                execution_time_ms=160,
                message="Payment recovered successfully after bank gateway recovery!"
            )
        else:
            return ExecutionResult(
                transaction_id=transaction.transaction_id,
                action=action,
                execution_status="SOFT_FAILED",
                success=False,
                recovered_amount=Decimal("0.00"),
                gateway_response_code="ERR_BANK_TIMEOUT",
                execution_time_ms=300,
                message="Temporary bank failure persisted."
            )

    # 7. Default Soft Decline Retry Simulation
    is_success = rng.random() < 0.60
    if is_success:
        return ExecutionResult(
            transaction_id=transaction.transaction_id,
            action=action,
            execution_status="RECOVERED",
            success=True,
            recovered_amount=transaction.amount,
            gateway_response_code="200_SUCCESS",
            execution_time_ms=190,
            message="Payment recovered successfully."
        )
    else:
        return ExecutionResult(
            transaction_id=transaction.transaction_id,
            action=action,
            execution_status="SOFT_FAILED",
            success=False,
            recovered_amount=Decimal("0.00"),
            gateway_response_code="ERR_GENERIC_SOFT_DECLINE",
            execution_time_ms=150,
            message="Gateway soft decline."
        )


def execute_recovery(
    transaction: Transaction,
    ai_diagnosis: AIDiagnosisResult,
    rule_validation: RuleValidationResult,
    db_path: str = DATABASE_PATH
) -> ExecutionResult:
    """
    Executes a recovery action strictly subject to Safety Rule Engine validation.

    CRITICAL SAFETY RULES:
    1. IF rule_validation.is_allowed is False: NO RECOVERY ACTION IS EXECUTED.
    2. IF rule_validation.is_allowed is True: Execute ONLY rule_validation.final_action.
       NEVER execute the original AI recommendation if the Rule Engine modified or capped it.
    """
    timestamp = get_utc_now_iso()

    # Safety Guardrail Check
    if not rule_validation.is_allowed:
        action_to_execute = RecoveryActionType.NO_ACTION_BLOCK
        discount_to_apply = 0.0
    else:
        # Must execute final_action (modified or approved by Rule Engine)
        action_to_execute = rule_validation.final_action
        discount_to_apply = rule_validation.modified_discount_pct

    # Run deterministic simulator
    result = simulate_recovery_attempt(
        transaction=transaction,
        action=action_to_execute,
        discount_pct=discount_to_apply
    )

    # Update Transaction state in database
    is_payment_retry = _to_enum_val(action_to_execute) in [
        RecoveryActionType.SMART_RETRY.value,
        RecoveryActionType.INCENTIVIZED_RETRY.value
    ]
    new_attempts = transaction.attempt_count + (1 if is_payment_retry else 0)

    if result.success and result.execution_status == "RECOVERED":
        new_status = TransactionStatus.RECOVERED
    elif result.execution_status == "HARD_FAILED" or new_attempts >= transaction.max_attempts_allowed:
        new_status = TransactionStatus.UNRECOVERABLE
    else:
        new_status = TransactionStatus.FAILED

    update_transaction_status(
        transaction_id=transaction.transaction_id,
        new_status=new_status,
        new_attempt_count=new_attempts,
        db_path=db_path
    )

    # Create Audit Logs
    audit_logs: list[AuditLog] = [
        AuditLog(
            log_id=f"audit_rule_{transaction.transaction_id}_{int(datetime.now(timezone.utc).timestamp()*1000)}",
            transaction_id=transaction.transaction_id,
            actor="Rule_Engine",
            action_taken="RULE_VALIDATION_COMPLETED",
            previous_status=str(transaction.status),
            new_status=str(transaction.status),
            details_json=json.dumps(rule_validation.audit_event_details, default=str),
            timestamp=timestamp
        ),
        AuditLog(
            log_id=f"audit_exec_{transaction.transaction_id}_{int(datetime.now(timezone.utc).timestamp()*1000)+1}",
            transaction_id=transaction.transaction_id,
            actor="Executor",
            action_taken=f"RECOVERY_EXECUTION_{result.execution_status}",
            previous_status=str(transaction.status),
            new_status=str(new_status),
            details_json=json.dumps(result.model_dump(), default=str),
            timestamp=timestamp
        )
    ]

    insert_audit_logs(audit_logs, db_path)
    return result
