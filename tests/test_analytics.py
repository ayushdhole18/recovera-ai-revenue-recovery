import os
import tempfile
import pytest
from decimal import Decimal
from app.core.models import (
    Merchant, Customer, Transaction, BusinessRule, AuditLog,
    TransactionStatus, FailureReason, DeclineCategory, RecoveryActionType,
    AIDiagnosisResult, RuleValidationResult, ExecutionResult
)
from app.core.database import (
    init_db, insert_merchants, insert_customers, insert_transactions, insert_audit_logs
)
from app.services.analytics import (
    calculate_transaction_recovery_rate, calculate_overall_transaction_recovery_rate,
    calculate_revenue_recovery_rate, calculate_average_recovered_value,
    get_transaction_audit_timeline, get_revenue_leakage_breakdown,
    get_action_performance_breakdown, process_batch_recovery
)


def test_recovery_rate_calculations_valid():
    rec_rate = calculate_transaction_recovery_rate(5, 10)
    assert rec_rate == 50.0

    overall_rate = calculate_overall_transaction_recovery_rate(5, 20)
    assert overall_rate == 25.0

    rev_rate = calculate_revenue_recovery_rate(Decimal("250.00"), Decimal("500.00"))
    assert rev_rate == 50.0

    avg_val = calculate_average_recovered_value(Decimal("300.00"), 3)
    assert avg_val == Decimal("100.00")


def test_recovery_rates_zero_denominator_safe():
    assert calculate_transaction_recovery_rate(5, 0) == 0.0
    assert calculate_overall_transaction_recovery_rate(5, 0) == 0.0
    assert calculate_revenue_recovery_rate(Decimal("100.00"), Decimal("0.00")) == 0.0
    assert calculate_average_recovered_value(Decimal("100.00"), 0) == Decimal("0.00")


def test_audit_timeline_investigation_helper():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        init_db(temp_db_path)

        mch = Merchant(merchant_id="mch_tl", name="TL Shop", email="tl@shop.com")
        cust = Customer(customer_id="cust_tl", merchant_id="mch_tl", name="TL User", email="tl@cust.com")
        tx = Transaction(
            transaction_id="tx_tl_001", merchant_id="mch_tl", customer_id="cust_tl",
            amount=Decimal("150.00"), status=TransactionStatus.FAILED
        )
        insert_merchants([mch], temp_db_path)
        insert_customers([cust], temp_db_path)
        insert_transactions([tx], temp_db_path)

        logs = [
            AuditLog(log_id="l1", transaction_id="tx_tl_001", actor="Detector", action_taken="RECOVERY_DETECTED", timestamp="2026-09-03T10:00:00Z"),
            AuditLog(log_id="l2", transaction_id="tx_tl_001", actor="AI_Agent", action_taken="AI_DIAGNOSIS_COMPLETED", timestamp="2026-09-03T10:00:01Z"),
            AuditLog(log_id="l3", transaction_id="tx_tl_001", actor="Executor", action_taken="PAYMENT_RECOVERED", timestamp="2026-09-03T10:00:02Z")
        ]
        insert_audit_logs(logs, temp_db_path)

        timeline = get_transaction_audit_timeline("tx_tl_001", temp_db_path)
        assert len(timeline) == 3
        assert timeline[0]["action_taken"] == "RECOVERY_DETECTED"
        assert timeline[1]["action_taken"] == "AI_DIAGNOSIS_COMPLETED"
        assert timeline[2]["action_taken"] == "PAYMENT_RECOVERED"

    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except OSError:
                pass


def test_revenue_leakage_breakdown():
    tx1 = Transaction(
        transaction_id="tx_lk_1", merchant_id="mch_1", customer_id="cust_1",
        amount=Decimal("100.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS, decline_category=DeclineCategory.SOFT_DECLINE
    )
    tx2 = Transaction(
        transaction_id="tx_lk_2", merchant_id="mch_1", customer_id="cust_1",
        amount=Decimal("200.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE
    )
    exec_res1 = ExecutionResult(
        transaction_id="tx_lk_1", action=RecoveryActionType.SMART_RETRY, execution_status="RECOVERED",
        success=True, recovered_amount=Decimal("100.00"), message="Success"
    )

    breakdown = get_revenue_leakage_breakdown([tx1, tx2], {"tx_lk_1": exec_res1}, group_by_field="failure_reason")
    assert len(breakdown) == 2
    assert breakdown[0].category_key == "FRAUD_STOLEN_CARD"
    assert breakdown[0].failed_revenue == Decimal("200.00")
    assert breakdown[1].category_key == "INSUFFICIENT_FUNDS"
    assert breakdown[1].recovered_revenue == Decimal("100.00")


def test_action_performance_breakdown():
    ai_diags = {
        "tx_1": AIDiagnosisResult(transaction_id="tx_1", failure_diagnosis="Soft", failure_category=DeclineCategory.SOFT_DECLINE, recovery_probability=0.8, recommended_action=RecoveryActionType.SMART_RETRY, reasoning="Low risk")
    }
    rule_vals = {
        "tx_1": RuleValidationResult(is_allowed=True, original_action=RecoveryActionType.SMART_RETRY, final_action=RecoveryActionType.SMART_RETRY, explanation="Approved")
    }
    exec_results = {
        "tx_1": ExecutionResult(transaction_id="tx_1", action=RecoveryActionType.SMART_RETRY, execution_status="RECOVERED", success=True, recovered_amount=Decimal("100.00"), message="Recovered")
    }

    perf = get_action_performance_breakdown(ai_diags, rule_vals, exec_results)
    smart_item = next(item for item in perf if item.action == "SMART_RETRY")
    assert smart_item.number_recommended == 1
    assert smart_item.successful_recoveries == 1
    assert smart_item.recovered_revenue == Decimal("100.00")
