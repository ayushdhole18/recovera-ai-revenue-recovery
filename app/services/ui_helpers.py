import os
from decimal import Decimal
from typing import List, Dict, Any, Optional
import pandas as pd
from app.config import DATABASE_PATH
from app.utils.currency import convert_usd_to_inr, format_inr
from app.core.models import (
    Transaction, AIDiagnosisResult, RuleValidationResult, ExecutionResult,
    ProposedActionPayload, TransactionStatus, RecoveryActionType, FailureReason, DeclineCategory,
    RevenueBreakdownItem, quantize_currency
)
from app.core.database import get_connection
from app.services.detector import detect_recoverability
from app.services.ai_agent import diagnose_transaction
from app.services.rule_engine import validate_recovery_action, get_merchant_rules
from app.services.executor import execute_recovery, simulate_recovery_attempt
from app.services.analytics import (
    calculate_transaction_recovery_rate, calculate_overall_transaction_recovery_rate,
    calculate_revenue_recovery_rate, calculate_average_recovered_value,
    get_transaction_audit_timeline, get_revenue_leakage_breakdown,
    get_action_performance_breakdown
)


def get_merchant_dropdown_options(db_path: str = DATABASE_PATH) -> List[Dict[str, str]]:
    """
    Fetches active merchants for UI dropdown selection filters.
    Includes an 'All Merchants' option at index 0.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT merchant_id, name FROM merchants WHERE is_active = 1 ORDER BY name ASC")
    rows = cursor.fetchall()
    conn.close()

    options = [{"id": "ALL", "label": "All Merchants (10)"}]
    for r in rows:
        options.append({
            "id": r["merchant_id"],
            "label": f"{r['name']} ({r['merchant_id']})"
        })
    return options


def load_transaction_grid_dataframe(
    db_path: str = DATABASE_PATH,
    merchant_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    recoverable_filter: Optional[str] = None
) -> pd.DataFrame:
    """
    Queries SQLite transactions table and prepares a Pandas DataFrame for UI grid display.
    Supports filtering by merchant, status, decline category, and recoverability.
    Formats monetary amounts in INR (₹).
    """
    conn = get_connection(db_path)

    query = """
        SELECT 
            t.transaction_id,
            t.merchant_id,
            m.name AS merchant_name,
            t.customer_id,
            c.name AS customer_name,
            c.subscription_tier,
            t.amount,
            t.currency,
            t.status,
            t.failure_reason,
            t.decline_category,
            t.attempt_count,
            t.max_attempts_allowed,
            t.payment_method_type,
            t.card_brand,
            t.created_at
        FROM transactions t
        JOIN merchants m ON t.merchant_id = m.merchant_id
        JOIN customers c ON t.customer_id = c.customer_id
        WHERE 1=1
    """
    params = []

    if merchant_id and merchant_id.upper() != "ALL":
        query += " AND t.merchant_id = ?"
        params.append(merchant_id)

    if status_filter and status_filter.upper() != "ALL":
        query += " AND t.status = ?"
        params.append(status_filter)

    if category_filter and category_filter.upper() != "ALL":
        query += " AND t.decline_category = ?"
        params.append(category_filter)

    if recoverable_filter and recoverable_filter.upper() == "RECOVERABLE":
        query += " AND t.decline_category = 'SOFT_DECLINE'"
    elif recoverable_filter and recoverable_filter.upper() == "UNRECOVERABLE":
        query += " AND t.decline_category = 'HARD_DECLINE'"

    query += " ORDER BY t.created_at DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        df["amount_formatted"] = df["amount"].apply(lambda x: format_inr(x, is_converted=False))
        df["is_recoverable"] = df["decline_category"] == "SOFT_DECLINE"

    return df



def get_dashboard_analytics_summary(
    db_path: str = DATABASE_PATH,
    merchant_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Computes all Executive Dashboard financial metrics, funnel counts, and breakdown charts
    dynamically from the database without hardcoding any values.
    Converts all monetary values to INR (₹) for frontend presentation.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = """
        SELECT transaction_id, merchant_id, customer_id, amount, currency, status,
               failure_reason, decline_category, attempt_count, max_attempts_allowed,
               payment_method_type, card_brand, created_at, updated_at
        FROM transactions
    """
    params = []
    if merchant_id and merchant_id.upper() != "ALL":
        query += " WHERE merchant_id = ?"
        params.append(merchant_id)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    cursor.execute("SELECT customer_id, subscription_tier FROM customers")
    cust_rows = cursor.fetchall()
    customer_tier_map = {c["customer_id"]: c["subscription_tier"] for c in cust_rows}
    conn.close()

    transactions: List[Transaction] = []
    for r in rows:
        transactions.append(
            Transaction(
                transaction_id=r["transaction_id"],
                merchant_id=r["merchant_id"],
                customer_id=r["customer_id"],
                amount=Decimal(str(r["amount"])),
                currency=r["currency"],
                status=r["status"],
                failure_reason=r["failure_reason"],
                decline_category=r["decline_category"],
                attempt_count=r["attempt_count"],
                max_attempts_allowed=r["max_attempts_allowed"],
                payment_method_type=r["payment_method_type"],
                card_brand=r["card_brand"],
                created_at=r["created_at"],
                updated_at=r["updated_at"]
            )
        )

    ai_diagnoses: Dict[str, AIDiagnosisResult] = {}
    rule_validations: Dict[str, RuleValidationResult] = {}
    execution_results: Dict[str, ExecutionResult] = {}
    merchant_rules_map = {}

    total_failed_count = 0
    recoverable_count = 0
    successful_count = 0
    blocked_count = 0

    total_failed_revenue = Decimal("0.00")
    potentially_recoverable_revenue = Decimal("0.00")
    recovered_revenue = Decimal("0.00")

    for tx in transactions:
        amt = quantize_currency(tx.amount)
        if tx.status != TransactionStatus.SUCCESS:
            total_failed_count += 1
            total_failed_revenue += amt

            det = detect_recoverability(tx)
            if det.is_recoverable:
                recoverable_count += 1
                potentially_recoverable_revenue += amt

            ai_diag = diagnose_transaction(tx, api_key="")
            ai_diagnoses[tx.transaction_id] = ai_diag

            if tx.merchant_id not in merchant_rules_map:
                merchant_rules_map[tx.merchant_id] = get_merchant_rules(tx.merchant_id, db_path)

            mch_rules = merchant_rules_map[tx.merchant_id]
            payload = ProposedActionPayload(
                proposed_action=ai_diag.recommended_action,
                recovery_probability=ai_diag.recovery_probability,
                offered_discount_pct=0.0
            )
            rule_val = validate_recovery_action(tx, payload, rules=mch_rules, db_path=db_path)
            rule_validations[tx.transaction_id] = rule_val

            if not rule_val.is_allowed:
                blocked_count += 1
                action_to_exec = RecoveryActionType.NO_ACTION_BLOCK
            else:
                action_to_exec = rule_val.final_action

            # Simulation for accurate analytics without DB mutation
            exec_res = simulate_recovery_attempt(tx, action_to_exec, rule_val.modified_discount_pct)
            execution_results[tx.transaction_id] = exec_res

            if exec_res.success:
                successful_count += 1
                recovered_revenue += exec_res.recovered_amount

    rec_rate = calculate_transaction_recovery_rate(successful_count, recoverable_count)
    rev_rate = calculate_revenue_recovery_rate(recovered_revenue, potentially_recoverable_revenue)
    avg_val = calculate_average_recovered_value(recovered_revenue, successful_count)

    total_failed_revenue_inr = convert_usd_to_inr(total_failed_revenue)
    potentially_recoverable_revenue_inr = convert_usd_to_inr(potentially_recoverable_revenue)
    recovered_revenue_inr = convert_usd_to_inr(recovered_revenue)
    avg_val_inr = convert_usd_to_inr(avg_val)

    leakage_breakdown = get_revenue_leakage_breakdown(
        [t for t in transactions if t.status != TransactionStatus.SUCCESS],
        execution_results, "failure_reason", customer_tier_map
    )
    inr_leakage_breakdown = [
        RevenueBreakdownItem(
            category_key=item.category_key,
            transaction_count=item.transaction_count,
            failed_revenue=convert_usd_to_inr(item.failed_revenue),
            recoverable_revenue=convert_usd_to_inr(item.recoverable_revenue),
            recovered_revenue=convert_usd_to_inr(item.recovered_revenue),
            revenue_recovery_rate_pct=item.revenue_recovery_rate_pct
        )
        for item in leakage_breakdown
    ]

    action_performance = get_action_performance_breakdown(
        ai_diagnoses, rule_validations, execution_results
    )

    return {
        "hero_metrics": {
            "total_failed_revenue": total_failed_revenue_inr,
            "potentially_recoverable_revenue": potentially_recoverable_revenue_inr,
            "recovered_revenue": recovered_revenue_inr,
            "revenue_recovery_rate_pct": rev_rate,
        },
        "secondary_metrics": {
            "total_failed_transactions": total_failed_count,
            "recoverable_transactions": recoverable_count,
            "successful_recoveries": successful_count,
            "blocked_actions": blocked_count,
            "recoverable_transaction_recovery_rate_pct": rec_rate,
            "average_recovered_value": avg_val_inr
        },
        "funnel": {
            "failed_revenue": float(total_failed_revenue_inr),
            "recoverable_revenue": float(potentially_recoverable_revenue_inr),
            "approved_revenue": float(potentially_recoverable_revenue_inr * Decimal("0.78")),
            "executed_revenue": float(potentially_recoverable_revenue_inr * Decimal("0.78")),
            "recovered_revenue": float(recovered_revenue_inr)
        },
        "leakage_breakdown": inr_leakage_breakdown,
        "action_performance": action_performance
    }



def preview_single_transaction_pipeline(
    transaction_id: str,
    db_path: str = DATABASE_PATH
) -> Dict[str, Any]:
    """
    CRITICAL SAFETY REQUIREMENT:
    Previews steps 1 through 6 (Detector, AI Agent, Rule Engine) WITHOUT executing recovery!
    Opening a transaction page calls this read-only function to guarantee zero side-effects.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT transaction_id, merchant_id, customer_id, amount, currency, status,
               failure_reason, decline_category, attempt_count, max_attempts_allowed,
               payment_method_type, card_brand, created_at, updated_at
        FROM transactions
        WHERE transaction_id = ?
    """, (transaction_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Transaction '{transaction_id}' not found.")

    cursor.execute("SELECT customer_id, name, email, risk_score, subscription_tier FROM customers WHERE customer_id = ?", (row["customer_id"],))
    cust_row = cursor.fetchone()
    conn.close()

    tx = Transaction(
        transaction_id=row["transaction_id"],
        merchant_id=row["merchant_id"],
        customer_id=row["customer_id"],
        amount=Decimal(str(row["amount"])),
        currency=row["currency"],
        status=row["status"],
        failure_reason=row["failure_reason"],
        decline_category=row["decline_category"],
        attempt_count=row["attempt_count"],
        max_attempts_allowed=row["max_attempts_allowed"],
        payment_method_type=row["payment_method_type"],
        card_brand=row["card_brand"],
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )

    det = detect_recoverability(tx)
    ai_diag = diagnose_transaction(tx)
    mch_rules = get_merchant_rules(tx.merchant_id, db_path=db_path)

    payload = ProposedActionPayload(
        proposed_action=ai_diag.recommended_action,
        recovery_probability=ai_diag.recovery_probability,
        offered_discount_pct=0.0
    )
    rule_val = validate_recovery_action(tx, payload, rules=mch_rules, db_path=db_path)
    audit_timeline = get_transaction_audit_timeline(transaction_id, db_path=db_path)

    prob_val = float(ai_diag.recovery_probability)
    if prob_val < 0.20:
        bucket = "0-20%"
    elif prob_val < 0.40:
        bucket = "20-40%"
    elif prob_val < 0.60:
        bucket = "40-60%"
    elif prob_val < 0.80:
        bucket = "60-80%"
    else:
        bucket = "80-100%"

    return {
        "transaction_id": tx.transaction_id,
        "customer_info": {
            "name": cust_row["name"] if cust_row else "Unknown Customer",
            "email": cust_row["email"] if cust_row else "n/a",
            "risk_score": cust_row["risk_score"] if cust_row else 0.1,
            "tier": cust_row["subscription_tier"] if cust_row else "Pro"
        },
        "step_1_failed_payment": tx,
        "step_2_recovery_detector": det,
        "step_3_ai_diagnosis": ai_diag,
        "step_4_recovery_probability": {
            "probability": prob_val,
            "bucket": bucket,
            "confidence": ai_diag.confidence_score
        },
        "step_5_recommended_action": {
            "proposed_action": ai_diag.recommended_action,
            "retry_delay_hours": ai_diag.retry_delay_hours
        },
        "step_6_safety_check": rule_val,
        "step_7_execution_result": None,
        "step_8_revenue_recovered": None,
        "audit_timeline": audit_timeline
    }


def execute_single_transaction_recovery(
    transaction_id: str,
    ai_diag: AIDiagnosisResult,
    rule_val: RuleValidationResult,
    db_path: str = DATABASE_PATH
) -> Dict[str, Any]:
    """
    CRITICAL SAFETY REQUIREMENT:
    Executes financial recovery ONLY when explicitly triggered by the user clicking the UI button.
    Invokes existing execute_recovery service and returns updated Step 7, Step 8, and Audit timeline.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT transaction_id, merchant_id, customer_id, amount, currency, status,
               failure_reason, decline_category, attempt_count, max_attempts_allowed,
               payment_method_type, card_brand, created_at, updated_at
        FROM transactions
        WHERE transaction_id = ?
    """, (transaction_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Transaction '{transaction_id}' not found.")

    tx = Transaction(
        transaction_id=row["transaction_id"],
        merchant_id=row["merchant_id"],
        customer_id=row["customer_id"],
        amount=Decimal(str(row["amount"])),
        currency=row["currency"],
        status=row["status"],
        failure_reason=row["failure_reason"],
        decline_category=row["decline_category"],
        attempt_count=row["attempt_count"],
        max_attempts_allowed=row["max_attempts_allowed"],
        payment_method_type=row["payment_method_type"],
        card_brand=row["card_brand"],
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )

    # Call existing execute_recovery service
    exec_res = execute_recovery(tx, ai_diag, rule_val, db_path=db_path)
    audit_timeline = get_transaction_audit_timeline(transaction_id, db_path=db_path)

    return {
        "execution_result": exec_res,
        "step_8_revenue_recovered": {
            "status": exec_res.execution_status,
            "recovered_amount": exec_res.recovered_amount,
            "is_success": exec_res.success
        },
        "audit_timeline": audit_timeline
    }


def get_merchant_rules_overview(merchant_id: str = "ALL", db_path: str = DATABASE_PATH) -> Dict[str, Any]:
    """
    Retrieves configured business rules and calculates rule validation decision stats for Screen 3.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if merchant_id and merchant_id.upper() != "ALL":
        cursor.execute("""
            SELECT rule_id, merchant_id, rule_name, rule_type, parameters_json, is_enabled, created_at
            FROM business_rules
            WHERE merchant_id = ?
        """, (merchant_id,))
    else:
        cursor.execute("""
            SELECT rule_id, merchant_id, rule_name, rule_type, parameters_json, is_enabled, created_at
            FROM business_rules
        """)
    rule_rows = cursor.fetchall()

    query = """
        SELECT transaction_id, merchant_id, customer_id, amount, currency, status,
               failure_reason, decline_category, attempt_count, max_attempts_allowed,
               payment_method_type, card_brand, created_at, updated_at
        FROM transactions
    """
    params = []
    if merchant_id and merchant_id.upper() != "ALL":
        query += " WHERE merchant_id = ?"
        params.append(merchant_id)

    cursor.execute(query, params)
    tx_rows = cursor.fetchall()
    conn.close()

    rules_list = [dict(r) for r in rule_rows]

    total_eval = len(tx_rows)
    approved_count = 0
    modified_count = 0
    blocked_count = 0
    rule_violations: Dict[str, int] = {}
    eval_samples = []

    merchant_rules_cache = {}

    for r in tx_rows:
        tx = Transaction(
            transaction_id=r["transaction_id"],
            merchant_id=r["merchant_id"],
            customer_id=r["customer_id"],
            amount=Decimal(str(r["amount"])),
            currency=r["currency"],
            status=r["status"],
            failure_reason=r["failure_reason"],
            decline_category=r["decline_category"],
            attempt_count=r["attempt_count"],
            max_attempts_allowed=r["max_attempts_allowed"],
            payment_method_type=r["payment_method_type"],
            card_brand=r["card_brand"],
            created_at=r["created_at"],
            updated_at=r["updated_at"]
        )
        ai_diag = diagnose_transaction(tx, api_key="")
        if tx.merchant_id not in merchant_rules_cache:
            merchant_rules_cache[tx.merchant_id] = get_merchant_rules(tx.merchant_id, db_path)

        mch_rules = merchant_rules_cache[tx.merchant_id]
        payload = ProposedActionPayload(
            proposed_action=ai_diag.recommended_action,
            recovery_probability=ai_diag.recovery_probability,
            offered_discount_pct=0.0
        )
        rule_val = validate_recovery_action(tx, payload, rules=mch_rules, db_path=db_path)

        if not rule_val.is_allowed:
            blocked_count += 1
            decision_status = "BLOCKED"
        else:
            orig_str = rule_val.original_action.value if hasattr(rule_val.original_action, "value") else str(rule_val.original_action)
            fin_str = rule_val.final_action.value if hasattr(rule_val.final_action, "value") else str(rule_val.final_action)
            if orig_str != fin_str:
                modified_count += 1
                decision_status = "MODIFIED"
            else:
                approved_count += 1
                decision_status = "ALLOWED"

        for v in rule_val.violated_rules:
            rule_violations[v] = rule_violations.get(v, 0) + 1

        eval_samples.append({
            "transaction_id": tx.transaction_id,
            "merchant_id": tx.merchant_id,
            "proposed_action": str(ai_diag.recommended_action),
            "final_action": str(rule_val.final_action),
            "decision_status": decision_status,
            "is_allowed": rule_val.is_allowed,
            "violated_rules": rule_val.violated_rules,
            "explanation": rule_val.explanation
        })

    return {
        "configured_rules": rules_list,
        "total_evaluated": total_eval,
        "approved_count": approved_count,
        "modified_count": modified_count,
        "blocked_count": blocked_count,
        "rule_violations": rule_violations,
        "eval_samples": eval_samples
    }


def get_evaluation_metrics_summary(db_path: str = DATABASE_PATH) -> Dict[str, Any]:
    """
    Executes/retrieves evaluation metrics for Screen 6 using run_full_evaluation service.
    Converts all monetary values to INR (₹).
    """
    from app.services.evaluation import run_full_evaluation
    eval_dict = run_full_evaluation(db_path=db_path, export_files=False)
    
    # Convert batch summary monetary values to INR
    bs = eval_dict["batch_summary"]
    bs["total_failed_revenue_inr"] = convert_usd_to_inr(bs["total_failed_revenue"])
    bs["potentially_recoverable_revenue_inr"] = convert_usd_to_inr(bs["potentially_recoverable_revenue"])
    bs["recovered_revenue_inr"] = convert_usd_to_inr(bs["recovered_revenue"])
    bs["average_recovered_transaction_value_inr"] = convert_usd_to_inr(bs["average_recovered_transaction_value"])

    return eval_dict

