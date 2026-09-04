import json
import sqlite3
from typing import List, Optional, Dict, Any
from app.config import DATABASE_PATH
from app.core.database import get_connection
from app.core.models import (
    Transaction, BusinessRule, ProposedActionPayload,
    RuleValidationResult, RecoveryActionType, TransactionStatus,
    FailureReason, DeclineCategory
)


def get_merchant_rules(merchant_id: str, db_path: str = DATABASE_PATH) -> List[BusinessRule]:
    """Fetches enabled business rules for a specific merchant from SQLite database."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT rule_id, merchant_id, rule_name, rule_type, parameters_json, is_enabled, created_at
        FROM business_rules
        WHERE merchant_id = ? AND is_enabled = 1
        """,
        (merchant_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    rules: List[BusinessRule] = []
    for row in rows:
        rules.append(BusinessRule(**dict(row)))
    return rules


def is_hour_in_quiet_window(current_hour: int, start_hour: int, end_hour: int) -> bool:
    """
    Checks if a given UTC hour (0-23) falls within quiet hours.
    Handles overnight windows (e.g. 22:00 to 06:00) and same-day windows (e.g. 01:00 to 05:00).
    """
    if start_hour > end_hour:
        # Overnight window (e.g. 22 to 6 -> 22,23,0,1,2,3,4,5)
        return current_hour >= start_hour or current_hour < end_hour
    else:
        # Same day window (e.g. 1 to 5)
        return start_hour <= current_hour < end_hour


def validate_recovery_action(
    transaction: Transaction,
    proposed_payload: ProposedActionPayload,
    rules: Optional[List[BusinessRule]] = None,
    db_path: str = DATABASE_PATH
) -> RuleValidationResult:
    """
    Deterministically validates a proposed recovery action against business rules.
    This module serves as the final authority before financial action execution.

    AI proposals NEVER bypass this layer.
    """
    if rules is None:
        rules = get_merchant_rules(transaction.merchant_id, db_path)

    # Config defaults
    max_retries = transaction.max_attempts_allowed
    allow_hard_decline_retry = False
    min_probability = 0.15
    max_discount_pct = 20.0
    quiet_hours_start = 22
    quiet_hours_end = 6
    quiet_hours_enabled = False

    # Extract parameters from merchant rules
    for rule in rules:
        try:
            params = json.loads(rule.parameters_json)
        except Exception:
            params = {}

        r_type = rule.rule_type.upper()
        if r_type == "MAX_RETRIES":
            max_retries = int(params.get("max_retries", max_retries))
        elif r_type == "HARD_DECLINE_BLOCK":
            allow_hard_decline_retry = bool(params.get("allow_stolen_card_retry", False))
        elif r_type == "MIN_PROBABILITY":
            min_probability = float(params.get("min_probability", min_probability))
        elif r_type == "MAX_DISCOUNT_PCT":
            max_discount_pct = float(params.get("max_discount_pct", max_discount_pct))
        elif r_type == "QUIET_HOURS":
            quiet_hours_enabled = True
            quiet_hours_start = int(params.get("quiet_hours_start", 22))
            quiet_hours_end = int(params.get("quiet_hours_end", 6))

    violated_rules: List[str] = []
    explanations: List[str] = []

    # 1. Check ALREADY_RECOVERED Rule
    status_str = str(transaction.status).upper()
    if status_str in [TransactionStatus.SUCCESS.value, TransactionStatus.RECOVERED.value]:
        violated_rules.append("ALREADY_RECOVERED")
        explanations.append("Transaction is already successful or recovered. Further action prohibited.")

    # 2. Check HARD_DECLINE_BLOCK Rule
    reason_str = str(transaction.failure_reason).upper()
    cat_str = str(transaction.decline_category).upper()
    if not allow_hard_decline_retry:
        if (
            cat_str == DeclineCategory.HARD_DECLINE.value
            or reason_str in [FailureReason.FRAUD_STOLEN_CARD.value, FailureReason.ACCOUNT_CLOSED.value]
        ):
            violated_rules.append("HARD_DECLINE_BLOCK")
            explanations.append(f"Payment retries blocked for hard decline ({reason_str}).")

    # 3. Check MAX_RETRY_COUNT Rule
    if transaction.attempt_count >= max_retries:
        violated_rules.append("MAX_RETRY_COUNT")
        explanations.append(f"Attempt count ({transaction.attempt_count}) reached maximum allowed ({max_retries}).")

    # 4. Check MIN_PROBABILITY Rule
    if proposed_payload.recovery_probability < min_probability:
        violated_rules.append("MIN_PROBABILITY")
        explanations.append(
            f"Estimated recovery probability ({proposed_payload.recovery_probability:.2f}) "
            f"is below merchant threshold ({min_probability:.2f})."
        )

    # 5. Check MAX_DISCOUNT_PCT Rule
    discount_violation = False
    if proposed_payload.offered_discount_pct > max_discount_pct:
        discount_violation = True
        violated_rules.append("MAX_DISCOUNT_PCT")
        explanations.append(
            f"Offered discount ({proposed_payload.offered_discount_pct:.1f}%) "
            f"exceeds merchant cap ({max_discount_pct:.1f}%)."
        )

    # 6. Check QUIET_HOURS Rule
    quiet_hours_violation = False
    is_outreach_action = proposed_payload.proposed_action in [
        RecoveryActionType.DUNNING_EMAIL,
        RecoveryActionType.PAYMENT_LINK_SMS,
        RecoveryActionType.INCENTIVIZED_RETRY
    ]
    if (
        quiet_hours_enabled
        and proposed_payload.current_hour_utc is not None
        and is_outreach_action
        and is_hour_in_quiet_window(proposed_payload.current_hour_utc, quiet_hours_start, quiet_hours_end)
    ):
        quiet_hours_violation = True
        violated_rules.append("QUIET_HOURS")
        explanations.append(
            f"Outreach action ({proposed_payload.proposed_action}) blocked during quiet hours "
            f"({quiet_hours_start}:00-{quiet_hours_end}:00 UTC)."
        )

    # Determine Final Action & Result
    # Hard blocker rules force NO_ACTION_BLOCK
    hard_blockers = {"ALREADY_RECOVERED", "HARD_DECLINE_BLOCK", "MAX_RETRY_COUNT", "MIN_PROBABILITY"}
    has_hard_blocker = any(r in hard_blockers for r in violated_rules)

    if has_hard_blocker:
        is_allowed = False
        final_action = RecoveryActionType.NO_ACTION_BLOCK
        final_discount = 0.0
    elif discount_violation or quiet_hours_violation:
        # Modifiable violations: Safe alternative action or capped discount
        is_allowed = True
        final_discount = min(proposed_payload.offered_discount_pct, max_discount_pct)
        if quiet_hours_violation:
            # Shift outreach action to silent background retry
            final_action = RecoveryActionType.SMART_RETRY
            explanations.append("Action modified from outreach to silent background SMART_RETRY due to quiet hours.")
        else:
            final_action = proposed_payload.proposed_action
            explanations.append(f"Discount capped to merchant limit ({final_discount:.1f}%).")
    else:
        is_allowed = True
        final_action = proposed_payload.proposed_action
        final_discount = proposed_payload.offered_discount_pct
        explanations.append("Action approved without modifications.")

    audit_event_details = {
        "transaction_id": transaction.transaction_id,
        "merchant_id": transaction.merchant_id,
        "original_action": str(proposed_payload.proposed_action),
        "final_action": str(final_action),
        "is_allowed": is_allowed,
        "violated_rules": violated_rules,
        "explanations": explanations,
        "offered_discount_pct": proposed_payload.offered_discount_pct,
        "final_discount_pct": final_discount,
        "recovery_probability": proposed_payload.recovery_probability
    }

    return RuleValidationResult(
        is_allowed=is_allowed,
        original_action=proposed_payload.proposed_action,
        final_action=final_action,
        modified_discount_pct=final_discount,
        violated_rules=violated_rules,
        explanation=" | ".join(explanations),
        audit_event_details=audit_event_details
    )
