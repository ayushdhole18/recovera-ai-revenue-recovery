import json
import os
from decimal import Decimal
from typing import List, Dict, Any, Optional
from pathlib import Path
from app.config import DATABASE_PATH, DATA_DIR
from app.core.models import (
    Transaction, AIDiagnosisResult, RuleValidationResult, ExecutionResult,
    EvaluationMetrics, SafetyMetrics, CalibrationBucket, BatchRecoverySummary,
    quantize_currency, RecoveryActionType, TransactionStatus, ProposedActionPayload
)
from app.core.database import get_connection, init_db
from app.services.detector import detect_recoverability
from app.services.ai_agent import diagnose_transaction
from app.services.rule_engine import validate_recovery_action, get_merchant_rules
from app.services.executor import simulate_recovery_attempt
from app.services.analytics import (
    calculate_transaction_recovery_rate, calculate_overall_transaction_recovery_rate,
    calculate_revenue_recovery_rate, calculate_average_recovered_value,
    get_revenue_leakage_breakdown, get_action_performance_breakdown
)


def evaluate_ai_predictions(
    ai_diagnoses: Dict[str, AIDiagnosisResult],
    execution_results: Dict[str, ExecutionResult]
) -> EvaluationMetrics:
    """
    Evaluates AI predicted probabilities vs actual simulator outcomes.
    Calculates Mean Absolute Error (MAE) and 5 calibration probability buckets.
    """
    if not ai_diagnoses:
        return EvaluationMetrics()

    total_preds = len(ai_diagnoses)
    prob_sum = 0.0
    actual_recovered_count = 0
    abs_error_sum = 0.0

    gemini_count = 0
    fallback_count = 0
    gemini_rev = Decimal("0.00")
    fallback_rev = Decimal("0.00")

    bucket_defs = [
        ("0-20%", 0.0, 0.20),
        ("20-40%", 0.20, 0.40),
        ("40-60%", 0.40, 0.60),
        ("60-80%", 0.60, 0.80),
        ("80-100%", 0.80, 1.00)
    ]

    bucket_data = {
        b[0]: {"min": b[1], "max": b[2], "count": 0, "prob_sum": 0.0, "actual_count": 0}
        for b in bucket_defs
    }

    for tx_id, diag in ai_diagnoses.items():
        prob = float(diag.recovery_probability)
        prob_sum += prob

        exec_res = execution_results.get(tx_id)
        actual_outcome = 1.0 if (exec_res and exec_res.success) else 0.0
        if actual_outcome == 1.0:
            actual_recovered_count += 1

        abs_error_sum += abs(prob - actual_outcome)

        if diag.is_fallback:
            fallback_count += 1
            if exec_res and exec_res.success:
                fallback_rev += quantize_currency(exec_res.recovered_amount)
        else:
            gemini_count += 1
            if exec_res and exec_res.success:
                gemini_rev += quantize_currency(exec_res.recovered_amount)

        for b_label, b_min, b_max in bucket_defs:
            if b_label == "80-100%":
                match = (b_min <= prob <= b_max)
            else:
                match = (b_min <= prob < b_max)

            if match:
                bucket_data[b_label]["count"] += 1
                bucket_data[b_label]["prob_sum"] += prob
                if actual_outcome == 1.0:
                    bucket_data[b_label]["actual_count"] += 1
                break

    avg_prob = prob_sum / total_preds if total_preds > 0 else 0.0
    outcome_rate = (actual_recovered_count / total_preds * 100.0) if total_preds > 0 else 0.0
    mae = abs_error_sum / total_preds if total_preds > 0 else 0.0

    calibration_buckets: List[CalibrationBucket] = []
    for b_label, b_min, b_max in bucket_defs:
        b_info = bucket_data[b_label]
        b_cnt = b_info["count"]
        b_avg_p = (b_info["prob_sum"] / b_cnt) if b_cnt > 0 else 0.0
        b_act_r = (b_info["actual_count"] / b_cnt * 100.0) if b_cnt > 0 else 0.0

        calibration_buckets.append(
            CalibrationBucket(
                bucket_label=b_label,
                min_prob=b_min,
                max_prob=b_max,
                prediction_count=b_cnt,
                avg_predicted_probability=round(b_avg_p, 4),
                actual_recovery_rate_pct=round(b_act_r, 2)
            )
        )

    pop_desc = f"All {total_preds} evaluated failed transactions in evaluation population"

    return EvaluationMetrics(
        total_predictions=total_preds,
        ai_prediction_population_description=pop_desc,
        avg_predicted_probability=round(avg_prob, 4),
        ai_prediction_outcome_rate_pct=round(outcome_rate, 2),
        actual_recovery_rate_pct=round(outcome_rate, 2),
        mean_absolute_error=round(mae, 4),
        calibration_buckets=calibration_buckets,
        gemini_diagnosis_count=gemini_count,
        fallback_diagnosis_count=fallback_count,
        gemini_recovered_revenue=gemini_rev,
        fallback_recovered_revenue=fallback_rev
    )


def evaluate_safety_metrics(
    ai_diagnoses: Dict[str, AIDiagnosisResult],
    rule_validations: Dict[str, RuleValidationResult]
) -> SafetyMetrics:
    """
    Evaluates safety rule engine enforcement metrics:
    approved vs modified vs blocked counts and non-mutually-exclusive rule violation frequencies.
    """
    total = len(ai_diagnoses)
    if total == 0:
        return SafetyMetrics()

    approved = 0
    modified = 0
    blocked = 0
    violation_counts: Dict[str, int] = {}

    for tx_id, diag in ai_diagnoses.items():
        rule_val = rule_validations.get(tx_id)
        if not rule_val:
            continue

        if not rule_val.is_allowed:
            blocked += 1
        else:
            orig_act = rule_val.original_action.value if hasattr(rule_val.original_action, "value") else str(rule_val.original_action)
            fin_act = rule_val.final_action.value if hasattr(rule_val.final_action, "value") else str(rule_val.final_action)
            if orig_act != fin_act:
                modified += 1
            else:
                approved += 1

        for v_rule in rule_val.violated_rules:
            violation_counts[v_rule] = violation_counts.get(v_rule, 0) + 1

    pct_b = (blocked / total * 100.0) if total > 0 else 0.0
    pct_m = (modified / total * 100.0) if total > 0 else 0.0

    return SafetyMetrics(
        total_ai_recommendations=total,
        approved_recommendations=approved,
        modified_recommendations=modified,
        blocked_recommendations=blocked,
        pct_blocked=round(pct_b, 2),
        pct_modified=round(pct_m, 2),
        rule_violation_frequency=violation_counts
    )


def run_full_evaluation(db_path: str = DATABASE_PATH, export_files: bool = True, use_gemini_if_available: bool = False) -> Dict[str, Any]:
    """
    Executes full evaluation on transactions in SQLite database cleanly.
    Uses read-only simulation to guarantee idempotency and prevent double-counting or DB mutation.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT transaction_id, merchant_id, customer_id, amount, currency, status,
               failure_reason, decline_category, attempt_count, max_attempts_allowed,
               payment_method_type, card_brand, created_at, updated_at
        FROM transactions
        WHERE status != 'SUCCESS'
    """)
    tx_rows = cursor.fetchall()

    cursor.execute("SELECT customer_id, subscription_tier FROM customers")
    cust_rows = cursor.fetchall()
    customer_tier_map = {c["customer_id"]: c["subscription_tier"] for c in cust_rows}
    conn.close()

    transactions: List[Transaction] = []
    for r in tx_rows:
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

    api_key_override = None if use_gemini_if_available else ""

    for tx in transactions:
        amt = quantize_currency(tx.amount)
        total_failed_revenue += amt

        det = detect_recoverability(tx)
        if det.is_recoverable:
            recoverable_count += 1
            potentially_recoverable_revenue += amt
        else:
            unrecoverable_count += 1

        ai_diag = diagnose_transaction(tx, api_key=api_key_override)
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

        # Read-only simulation for reproducible evaluation
        action_to_exec = RecoveryActionType.NO_ACTION_BLOCK if not rule_val.is_allowed else rule_val.final_action
        disc_to_apply = 0.0 if not rule_val.is_allowed else rule_val.modified_discount_pct
        exec_res = simulate_recovery_attempt(tx, action_to_exec, disc_to_apply)
        execution_results[tx.transaction_id] = exec_res

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

    batch_summary = BatchRecoverySummary(
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
        revenue_recovery_rate_pct=calculate_revenue_recovery_rate(recovered_revenue, potentially_recoverable_revenue),
        average_recovered_transaction_value=calculate_average_recovered_value(recovered_revenue, successful_count)
    )

    eval_metrics = evaluate_ai_predictions(ai_diagnoses, execution_results)
    safety_metrics = evaluate_safety_metrics(ai_diagnoses, rule_validations)
    leakage_by_reason = get_revenue_leakage_breakdown(transactions, execution_results, "failure_reason", customer_tier_map)
    action_performance = get_action_performance_breakdown(ai_diagnoses, rule_validations, execution_results)

    evaluation_report_dict = {
        "batch_summary": batch_summary.model_dump(),
        "evaluation_metrics": eval_metrics.model_dump(),
        "safety_metrics": safety_metrics.model_dump(),
        "revenue_leakage_by_reason": [item.model_dump() for item in leakage_by_reason],
        "action_performance": [item.model_dump() for item in action_performance]
    }

    if export_files:
        data_dir = Path(DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)

        json_path = data_dir / "evaluation_results.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(evaluation_report_dict, f, indent=2, default=str)

        md_path = data_dir / "evaluation_report.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(generate_markdown_report(batch_summary, eval_metrics, safety_metrics, leakage_by_reason, action_performance))

    return evaluation_report_dict


def generate_markdown_report(
    summary: BatchRecoverySummary,
    eval_m: EvaluationMetrics,
    safety_m: SafetyMetrics,
    leakage: List[Any],
    actions: List[Any]
) -> str:
    """Generates a detailed, transparent markdown evaluation report with explicit metric definitions and notes."""
    md = []
    md.append("# Recovera AI - Batch Recovery Evaluation Report\n")
    md.append("## 1. Executive Summary & Recovery Metrics\n")
    md.append(f"- **Total Failed Transactions Analyzed**: {summary.total_transactions_analyzed}")
    md.append(f"- **Potentially Recoverable Transactions**: {summary.recoverable_transactions} (classified by Detector)")
    md.append(f"- **Unrecoverable Transactions**: {summary.unrecoverable_transactions} (hard declines / permanent errors)")
    md.append(f"- **Total Failed Revenue (At Risk)**: ${summary.total_failed_revenue:,.2f}")
    md.append(f"- **Potentially Recoverable Revenue**: ${summary.potentially_recoverable_revenue:,.2f}")
    md.append(f"- **Revenue Recovered**: ${summary.recovered_revenue:,.2f}")
    md.append("")
    md.append("### Explicit Recovery Rate Metric Breakdown:")
    md.append(f"- **Recoverable Transaction Recovery Rate**: **{summary.recoverable_transaction_recovery_rate_pct:.2f}%** (`{summary.successful_recoveries} / {summary.recoverable_transactions}` recoverable transactions)")
    md.append(f"- **Overall Failed-Transaction Recovery Rate**: **{summary.overall_failed_transaction_recovery_rate_pct:.2f}%** (`{summary.successful_recoveries} / {summary.total_transactions_analyzed}` total failed transactions)")
    md.append(f"- **Revenue Recovery Rate**: **{summary.revenue_recovery_rate_pct:.2f}%** (`${summary.recovered_revenue:,.2f} / ${summary.potentially_recoverable_revenue:,.2f}` recoverable revenue)")
    md.append(f"- **Average Recovered Transaction Value**: **${summary.average_recovered_transaction_value:,.2f}** (`${summary.recovered_revenue:,.2f} / {summary.successful_recoveries}` recoveries)\n")

    md.append("## 2. Safety & Business Rule Enforcement Metrics\n")
    md.append(f"- **Total AI Recommendations Evaluated**: {safety_m.total_ai_recommendations}")
    md.append(f"- **Approved Recommendations**: {safety_m.approved_recommendations}")
    md.append(f"- **Modified Recommendations**: {safety_m.modified_recommendations} ({safety_m.pct_modified:.2f}%)")
    md.append(f"- **Blocked Recommendations**: {safety_m.blocked_recommendations} ({safety_m.pct_blocked:.2f}%)\n")

    md.append("### Rule Violation Frequency (Non-Mutually-Exclusive)\n")
    md.append("> *Note: A single proposed recovery action may violate multiple safety rules simultaneously. Therefore, total rule violations may exceed total blocked recommendations.*\n")
    for r_name, cnt in safety_m.rule_violation_frequency.items():
        md.append(f"- `{r_name}`: {cnt} violations")
    md.append("")

    md.append("## 3. AI Probability Calibration & Evaluation\n")
    md.append(f"- **Evaluation Population**: {eval_m.ai_prediction_population_description}")
    md.append(f"- **Average Predicted Probability**: {eval_m.avg_predicted_probability:.4f}")
    md.append(f"- **AI Prediction Outcome Rate**: **{eval_m.ai_prediction_outcome_rate_pct:.2f}%** (`{int(eval_m.ai_prediction_outcome_rate_pct * eval_m.total_predictions / 100)} / {eval_m.total_predictions}` total evaluated predictions)")
    md.append(f"- **Mean Absolute Error (MAE)**: **{eval_m.mean_absolute_error:.4f}**\n")
    md.append("> *Methodological Limitation Note: Probability estimates reflect uncalibrated synthetic heuristic recommendations. High MAE ({0:.4f}) indicates model overconfidence, which is expected for raw heuristic models before empirical calibration models are trained on real merchant payment data.*\n".format(eval_m.mean_absolute_error))

    md.append("| Probability Bucket | Predictions | Avg Predicted Prob | Actual Recovery Rate |")
    md.append("|--------------------|-------------|--------------------|----------------------|")
    for b in eval_m.calibration_buckets:
        md.append(f"| {b.bucket_label} | {b.prediction_count} | {b.avg_predicted_probability:.4f} | {b.actual_recovery_rate_pct:.2f}% |")
    md.append("")

    md.append("## 4. Source Breakdown (Gemini AI vs Fallback Heuristic Engine)\n")
    md.append(f"- **Gemini AI Diagnoses**: {eval_m.gemini_diagnosis_count} (Recovered: ${eval_m.gemini_recovered_revenue:,.2f})")
    md.append(f"- **Fallback Engine Diagnoses**: {eval_m.fallback_diagnosis_count} (Recovered: ${eval_m.fallback_recovered_revenue:,.2f})\n")
    md.append("> *Configuration Note: Offline evaluation run defaulted to the deterministic fallback engine (`is_fallback=True`) because `GEMINI_API_KEY` was omitted during benchmark execution to ensure offline speed, reproducibility, and zero API costs. Live execution uses Gemini 2.5 Flash when `GEMINI_API_KEY` is provided in `.env`.*\n")

    return "\n".join(md)
