from decimal import Decimal
from typing import List, Dict, Optional, Any
from app.config import DATABASE_PATH
from app.core.models import (
    Transaction, ExecutionResult, BatchRecoverySummary,
    TransactionStatus, ProposedActionPayload, quantize_currency,
    RevenueBreakdownItem, ActionPerformanceItem, RecoveryActionType,
    AIDiagnosisResult, RuleValidationResult, AuditLog
)
from app.core.database import get_connection, insert_audit_logs
from app.services.detector import detect_recoverability
from app.services.ai_agent import diagnose_transaction
from app.services.rule_engine import validate_recovery_action, get_merchant_rules
from app.services.executor import execute_recovery


def calculate_transaction_recovery_rate(successful_recovered_transactions: int, recoverable_transactions: int) -> float:
    """
    Calculates Recoverable Transaction Recovery Rate percentage:
    rate = (successful_recovered_transactions / recoverable_transactions) * 100.0
    """
    if recoverable_transactions <= 0:
        return 0.0
    return round((successful_recovered_transactions / recoverable_transactions) * 100.0, 2)


def calculate_overall_transaction_recovery_rate(successful_recovered_transactions: int, total_failed_transactions: int) -> float:
    """
    Calculates Overall Failed Transaction Recovery Rate percentage:
    rate = (successful_recovered_transactions / total_failed_transactions) * 100.0
    """
    if total_failed_transactions <= 0:
        return 0.0
    return round((successful_recovered_transactions / total_failed_transactions) * 100.0, 2)


def calculate_revenue_recovery_rate(recovered_revenue: Decimal, potentially_recoverable_revenue: Decimal) -> float:
    """
    Calculates Revenue Recovery Rate percentage:
    rate = (recovered_revenue / potentially_recoverable_revenue) * 100.0
    """
    rec = quantize_currency(recovered_revenue)
    pot = quantize_currency(potentially_recoverable_revenue)

    if pot <= Decimal("0.00"):
        return 0.0

    return round((float(rec) / float(pot)) * 100.0, 2)


def calculate_average_recovered_value(recovered_revenue: Decimal, successful_recoveries: int) -> Decimal:
    """
    Calculates average recovered transaction monetary value:
    avg = recovered_revenue / successful_recoveries
    """
    if successful_recoveries <= 0:
        return Decimal("0.00")
    return quantize_currency(quantize_currency(recovered_revenue) / Decimal(successful_recoveries))


def get_transaction_audit_timeline(transaction_id: str, db_path: str = DATABASE_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves complete chronological audit trail timeline for a given transaction_id from the database.
    
    NOTE: Reflects actual workflow audit events appended during real executions or seed generation.
    Read-only evaluation runs do NOT write audit events to preserve database state.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT log_id, transaction_id, actor, action_taken, previous_status, new_status, details_json, timestamp
        FROM audit_trail
        WHERE transaction_id = ?
        ORDER BY timestamp ASC, log_id ASC
        """,
        (transaction_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    timeline = []
    for r in rows:
        timeline.append({
            "log_id": r["log_id"],
            "transaction_id": r["transaction_id"],
            "actor": r["actor"],
            "action_taken": r["action_taken"],
            "previous_status": r["previous_status"],
            "new_status": r["new_status"],
            "details_json": r["details_json"],
            "timestamp": r["timestamp"]
        })
    return timeline


def get_revenue_leakage_breakdown(
    transactions: List[Transaction],
    execution_results: Dict[str, ExecutionResult],
    group_by_field: str = "failure_reason",
    customer_tier_map: Optional[Dict[str, str]] = None
) -> List[RevenueBreakdownItem]:
    """
    Groups failed revenue by failure_reason, decline_category, payment_method, merchant, or subscription_tier.
    """
    groups: Dict[str, Dict[str, Any]] = {}

    for tx in transactions:
        if group_by_field == "failure_reason":
            key = str(tx.failure_reason.value if hasattr(tx.failure_reason, "value") else tx.failure_reason)
        elif group_by_field == "decline_category":
            key = str(tx.decline_category.value if hasattr(tx.decline_category, "value") else tx.decline_category)
        elif group_by_field == "payment_method":
            key = str(tx.payment_method_type)
        elif group_by_field == "merchant":
            key = str(tx.merchant_id)
        elif group_by_field == "subscription_tier":
            key = customer_tier_map.get(tx.customer_id, "Pro") if customer_tier_map else "Pro"
        else:
            key = "OTHER"

        if key not in groups:
            groups[key] = {
                "count": 0,
                "failed_rev": Decimal("0.00"),
                "pot_rev": Decimal("0.00"),
                "rec_rev": Decimal("0.00")
            }

        amt = quantize_currency(tx.amount)
        groups[key]["count"] += 1
        groups[key]["failed_rev"] += amt

        # Check recoverability
        det = detect_recoverability(tx)
        if det.is_recoverable:
            groups[key]["pot_rev"] += amt

        # Check execution result
        exec_res = execution_results.get(tx.transaction_id)
        if exec_res and exec_res.success:
            groups[key]["rec_rev"] += quantize_currency(exec_res.recovered_amount)

    items: List[RevenueBreakdownItem] = []
    for k, v in groups.items():
        rate = calculate_revenue_recovery_rate(v["rec_rev"], v["pot_rev"])
        items.append(
            RevenueBreakdownItem(
                category_key=k,
                transaction_count=v["count"],
                failed_revenue=v["failed_rev"],
                recoverable_revenue=v["pot_rev"],
                recovered_revenue=v["rec_rev"],
                revenue_recovery_rate_pct=rate
            )
        )

    return sorted(items, key=lambda x: x.failed_revenue, reverse=True)


def get_action_performance_breakdown(
    ai_diagnoses: Dict[str, AIDiagnosisResult],
    rule_validations: Dict[str, RuleValidationResult],
    execution_results: Dict[str, ExecutionResult]
) -> List[ActionPerformanceItem]:
    """
    Calculates performance breakdown by RecoveryActionType.
    """
    actions_map: Dict[str, Dict[str, Any]] = {
        action.value: {
            "recommended": 0, "approved": 0, "blocked": 0,
            "executed": 0, "successful": 0, "recovered_rev": Decimal("0.00")
        }
        for action in RecoveryActionType
    }

    for tx_id, diag in ai_diagnoses.items():
        rec_action = diag.recommended_action.value if hasattr(diag.recommended_action, "value") else str(diag.recommended_action)
        if rec_action in actions_map:
            actions_map[rec_action]["recommended"] += 1

        rule_val = rule_validations.get(tx_id)
        exec_res = execution_results.get(tx_id)

        if rule_val:
            if not rule_val.is_allowed:
                actions_map[rec_action]["blocked"] += 1
            else:
                final_act = rule_val.final_action.value if hasattr(rule_val.final_action, "value") else str(rule_val.final_action)
                if final_act in actions_map:
                    actions_map[final_act]["approved"] += 1

        if exec_res:
            exec_act = exec_res.action.value if hasattr(exec_res.action, "value") else str(exec_res.action)
            if exec_act in actions_map:
                actions_map[exec_act]["executed"] += 1
                if exec_res.success:
                    actions_map[exec_act]["successful"] += 1
                    actions_map[exec_act]["recovered_rev"] += quantize_currency(exec_res.recovered_amount)

    performance_items: List[ActionPerformanceItem] = []
    for act_key, stats in actions_map.items():
        exec_count = stats["executed"]
        succ_count = stats["successful"]
        rate = round((succ_count / exec_count * 100.0), 2) if exec_count > 0 else 0.0

        performance_items.append(
            ActionPerformanceItem(
                action=act_key,
                number_recommended=stats["recommended"],
                number_approved=stats["approved"],
                number_blocked=stats["blocked"],
                number_executed=stats["executed"],
                successful_recoveries=stats["successful"],
                recovered_revenue=stats["recovered_rev"],
                recovery_rate_pct=rate
            )
        )

    return performance_items


def process_batch_recovery(
    transactions: List[Transaction],
    db_path: str = DATABASE_PATH,
    use_ai_fallback: bool = True
) -> BatchRecoverySummary:
    """
    Executes end-to-end batch recovery pipeline for hackathon evaluation:
    Transaction -> Detector -> AI Diagnosis/Fallback -> Rule Engine -> Executor -> Database Audit Log
    """
    total_analyzed = len(transactions)
    recoverable_count = 0
    unrecoverable_count = 0
    attempts_count = 0
    successful_count = 0
    failed_count = 0
    blocked_count = 0

    total_failed_revenue = Decimal("0.00")
    potentially_recoverable_revenue = Decimal("0.00")
    recovered_revenue = Decimal("0.00")

    merchant_rules_map = {}

    for tx in transactions:
        amount = quantize_currency(tx.amount)
        total_failed_revenue += amount

        detection = detect_recoverability(tx)
        if detection.is_recoverable:
            recoverable_count += 1
            potentially_recoverable_revenue += amount
        else:
            unrecoverable_count += 1

        ai_diagnosis = diagnose_transaction(
            transaction=tx,
            api_key="" if use_ai_fallback else None
        )

        if tx.merchant_id not in merchant_rules_map:
            merchant_rules_map[tx.merchant_id] = get_merchant_rules(tx.merchant_id, db_path)

        mch_rules = merchant_rules_map[tx.merchant_id]
        payload = ProposedActionPayload(
            proposed_action=ai_diagnosis.recommended_action,
            recovery_probability=ai_diagnosis.recovery_probability,
            offered_discount_pct=0.0
        )
        rule_val = validate_recovery_action(tx, payload, rules=mch_rules, db_path=db_path)
        exec_res = execute_recovery(tx, ai_diagnosis, rule_val, db_path=db_path)

        if exec_res.execution_status == "BLOCKED":
            blocked_count += 1
        elif exec_res.success and exec_res.execution_status == "RECOVERED":
            successful_count += 1
            attempts_count += 1
            recovered_revenue += exec_res.recovered_amount
        elif exec_res.execution_status in ["SOFT_FAILED", "HARD_FAILED"]:
            failed_count += 1
            attempts_count += 1

    rec_rate = calculate_transaction_recovery_rate(successful_count, recoverable_count)
    overall_rate = calculate_overall_transaction_recovery_rate(successful_count, total_analyzed)
    rev_rate = calculate_revenue_recovery_rate(recovered_revenue, potentially_recoverable_revenue)
    avg_val = calculate_average_recovered_value(recovered_revenue, successful_count)

    return BatchRecoverySummary(
        total_transactions_analyzed=total_analyzed,
        total_failed_transactions=total_analyzed,
        recoverable_transactions=recoverable_count,
        unrecoverable_transactions=unrecoverable_count,
        recovery_attempts=attempts_count,
        successful_recoveries=successful_count,
        failed_attempts=failed_count,
        blocked_actions=blocked_count,
        total_failed_revenue=total_failed_revenue,
        potentially_recoverable_revenue=potentially_recoverable_revenue,
        recovered_revenue=recovered_revenue,
        recoverable_transaction_recovery_rate_pct=rec_rate,
        overall_failed_transaction_recovery_rate_pct=overall_rate,
        transaction_recovery_rate_pct=rec_rate,
        revenue_recovery_rate_pct=rev_rate,
        average_recovered_transaction_value=avg_val
    )
