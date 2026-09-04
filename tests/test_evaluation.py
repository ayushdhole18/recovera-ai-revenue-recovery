import os
import tempfile
import pytest
from decimal import Decimal
from app.core.models import (
    Merchant, Customer, Transaction, AIDiagnosisResult, RuleValidationResult, ExecutionResult,
    TransactionStatus, FailureReason, DeclineCategory, RecoveryActionType
)
from app.core.database import init_db, insert_merchants, insert_customers, insert_transactions
from app.services.evaluation import (
    evaluate_ai_predictions, evaluate_safety_metrics, run_full_evaluation
)


def test_evaluate_ai_predictions():
    ai_diags = {
        "tx_1": AIDiagnosisResult(
            transaction_id="tx_1", failure_diagnosis="Soft", failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.80, recommended_action=RecoveryActionType.SMART_RETRY, reasoning="Soft", is_fallback=False
        ),
        "tx_2": AIDiagnosisResult(
            transaction_id="tx_2", failure_diagnosis="Hard", failure_category=DeclineCategory.HARD_DECLINE,
            recovery_probability=0.10, recommended_action=RecoveryActionType.NO_ACTION_BLOCK, reasoning="Hard", is_fallback=True
        )
    }

    exec_results = {
        "tx_1": ExecutionResult(
            transaction_id="tx_1", action=RecoveryActionType.SMART_RETRY, execution_status="RECOVERED",
            success=True, recovered_amount=Decimal("100.00"), message="Success"
        ),
        "tx_2": ExecutionResult(
            transaction_id="tx_2", action=RecoveryActionType.NO_ACTION_BLOCK, execution_status="BLOCKED",
            success=False, recovered_amount=Decimal("0.00"), message="Blocked"
        )
    }

    eval_m = evaluate_ai_predictions(ai_diags, exec_results)
    assert eval_m.total_predictions == 2
    assert eval_m.gemini_diagnosis_count == 1
    assert eval_m.fallback_diagnosis_count == 1
    assert eval_m.gemini_recovered_revenue == Decimal("100.00")
    assert eval_m.fallback_recovered_revenue == Decimal("0.00")
    assert len(eval_m.calibration_buckets) == 5
    assert eval_m.ai_prediction_outcome_rate_pct == 50.0
    # MAE calculation check: (|0.8 - 1.0| + |0.1 - 0.0|) / 2 = (0.2 + 0.1) / 2 = 0.15
    assert eval_m.mean_absolute_error == 0.15


def test_evaluate_safety_metrics():
    ai_diags = {
        "tx_1": AIDiagnosisResult(
            transaction_id="tx_1", failure_diagnosis="Soft", failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.80, recommended_action=RecoveryActionType.SMART_RETRY, reasoning="Test"
        ),
        "tx_2": AIDiagnosisResult(
            transaction_id="tx_2", failure_diagnosis="Hard", failure_category=DeclineCategory.HARD_DECLINE,
            recovery_probability=0.90, recommended_action=RecoveryActionType.SMART_RETRY, reasoning="Rogue"
        )
    }

    rule_vals = {
        "tx_1": RuleValidationResult(
            is_allowed=True, original_action=RecoveryActionType.SMART_RETRY, final_action=RecoveryActionType.SMART_RETRY,
            violated_rules=[], explanation="Approved"
        ),
        "tx_2": RuleValidationResult(
            is_allowed=False, original_action=RecoveryActionType.SMART_RETRY, final_action=RecoveryActionType.NO_ACTION_BLOCK,
            violated_rules=["HARD_DECLINE_BLOCK", "MIN_PROBABILITY"], explanation="Blocked hard decline"
        )
    }

    safety_m = evaluate_safety_metrics(ai_diags, rule_vals)
    assert safety_m.total_ai_recommendations == 2
    assert safety_m.approved_recommendations == 1
    assert safety_m.blocked_recommendations == 1
    assert safety_m.pct_blocked == 50.0
    # Non-mutually-exclusive rule violation checks
    assert safety_m.rule_violation_frequency.get("HARD_DECLINE_BLOCK") == 1
    assert safety_m.rule_violation_frequency.get("MIN_PROBABILITY") == 1


def test_full_evaluation_reproducibility():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        init_db(temp_db_path)

        mch = Merchant(merchant_id="mch_rep", name="Rep Merchant", email="r@mch.com")
        cust = Customer(customer_id="cust_rep", merchant_id="mch_rep", name="Rep Cust", email="r@cust.com")
        tx1 = Transaction(
            transaction_id="tx_rep_1", merchant_id="mch_rep", customer_id="cust_rep",
            amount=Decimal("100.00"), status=TransactionStatus.FAILED,
            failure_reason=FailureReason.INSUFFICIENT_FUNDS, decline_category=DeclineCategory.SOFT_DECLINE
        )
        insert_merchants([mch], temp_db_path)
        insert_customers([cust], temp_db_path)
        insert_transactions([tx1], temp_db_path)

        res1 = run_full_evaluation(db_path=temp_db_path, export_files=False)
        res2 = run_full_evaluation(db_path=temp_db_path, export_files=False)

        assert res1["batch_summary"]["recovered_revenue"] == res2["batch_summary"]["recovered_revenue"]
        assert res1["batch_summary"]["successful_recoveries"] == res2["batch_summary"]["successful_recoveries"]
        assert res1["batch_summary"]["recoverable_transaction_recovery_rate_pct"] == res2["batch_summary"]["recoverable_transaction_recovery_rate_pct"]
        assert res1["batch_summary"]["overall_failed_transaction_recovery_rate_pct"] == res2["batch_summary"]["overall_failed_transaction_recovery_rate_pct"]
        assert res1["evaluation_metrics"]["mean_absolute_error"] == res2["evaluation_metrics"]["mean_absolute_error"]

    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except OSError:
                pass
