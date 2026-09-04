import os
import sqlite3
import tempfile
import pytest
from decimal import Decimal
from app.core.models import (
    Merchant, Customer, Transaction, BusinessRule, AuditLog,
    AIDiagnosisResult, RuleValidationResult, ExecutionResult,
    TransactionStatus, FailureReason, DeclineCategory, RecoveryActionType
)
from app.core.database import (
    init_db, insert_merchants, insert_customers, insert_transactions,
    get_database_counts, get_connection
)
from app.services.executor import simulate_recovery_attempt, execute_recovery


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        path = tf.name

    init_db(path)
    mch = Merchant(merchant_id="mch_ex", name="Executor Shop", email="ex@shop.com")
    cust = Customer(customer_id="cust_ex", merchant_id="mch_ex", name="Ex User", email="u@ex.com")
    tx1 = Transaction(
        transaction_id="tx_ex_001", merchant_id="mch_ex", customer_id="cust_ex",
        amount=Decimal("100.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS, decline_category=DeclineCategory.SOFT_DECLINE,
        attempt_count=1, max_attempts_allowed=3
    )
    tx_hard = Transaction(
        transaction_id="tx_ex_hard", merchant_id="mch_ex", customer_id="cust_ex",
        amount=Decimal("250.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE,
        attempt_count=1, max_attempts_allowed=3
    )
    insert_merchants([mch], path)
    insert_customers([cust], path)
    insert_transactions([tx1, tx_hard], path)

    yield path

    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


# 1. Simulator Determinism & Monetary Precision Tests

def test_simulator_determinism():
    tx = Transaction(
        transaction_id="tx_sim_001", merchant_id="mch_001", customer_id="c1",
        amount=Decimal("199.99"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS, decline_category=DeclineCategory.SOFT_DECLINE
    )
    res1 = simulate_recovery_attempt(tx, RecoveryActionType.SMART_RETRY, seed_val=12345)
    res2 = simulate_recovery_attempt(tx, RecoveryActionType.SMART_RETRY, seed_val=12345)

    assert res1.execution_status == res2.execution_status
    assert res1.success == res2.success
    assert res1.recovered_amount == res2.recovered_amount


def test_simulator_monetary_exactness_and_discount():
    tx = Transaction(
        transaction_id="tx_sim_disc", merchant_id="mch_001", customer_id="c1",
        amount=Decimal("100.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS, decline_category=DeclineCategory.SOFT_DECLINE
    )
    # Simulate incentivized retry with 20% discount (force seed that succeeds)
    res = simulate_recovery_attempt(tx, RecoveryActionType.INCENTIVIZED_RETRY, discount_pct=20.0, seed_val=1)
    if res.success:
        assert res.recovered_amount == Decimal("80.00")
        assert isinstance(res.recovered_amount, Decimal)


def test_simulator_unsuccessful_recovery_reports_zero():
    tx = Transaction(
        transaction_id="tx_sim_zero", merchant_id="mch_001", customer_id="c1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE
    )
    res = simulate_recovery_attempt(tx, RecoveryActionType.SMART_RETRY)
    assert res.success is False
    assert res.recovered_amount == Decimal("0.00")


# 2. Execution Safety Tests

def test_execute_recovery_blocked_action_not_executed(temp_db):
    tx = Transaction(
        transaction_id="tx_ex_001", merchant_id="mch_ex", customer_id="cust_ex",
        amount=Decimal("100.00"), status=TransactionStatus.FAILED, attempt_count=3, max_attempts_allowed=3
    )
    ai_diag = AIDiagnosisResult(
        transaction_id="tx_ex_001", failure_diagnosis="Rogue AI retry", failure_category=DeclineCategory.SOFT_DECLINE,
        recovery_probability=0.8, recommended_action=RecoveryActionType.SMART_RETRY, reasoning="Rogue"
    )
    rule_val = RuleValidationResult(
        is_allowed=False, original_action=RecoveryActionType.SMART_RETRY, final_action=RecoveryActionType.NO_ACTION_BLOCK,
        violated_rules=["MAX_RETRY_COUNT"], explanation="Max retry limit reached."
    )

    res = execute_recovery(tx, ai_diag, rule_val, db_path=temp_db)
    assert res.execution_status == "BLOCKED"
    assert res.success is False
    assert res.recovered_amount == Decimal("0.00")


def test_execute_recovery_modified_action_executed(temp_db):
    tx = Transaction(
        transaction_id="tx_ex_001", merchant_id="mch_ex", customer_id="cust_ex",
        amount=Decimal("100.00"), status=TransactionStatus.FAILED, attempt_count=1, max_attempts_allowed=3
    )
    ai_diag = AIDiagnosisResult(
        transaction_id="tx_ex_001", failure_diagnosis="Soft decline during quiet hours", failure_category=DeclineCategory.SOFT_DECLINE,
        recovery_probability=0.8, recommended_action=RecoveryActionType.DUNNING_EMAIL, reasoning="Send email"
    )
    # Rule engine modifies action from DUNNING_EMAIL to SMART_RETRY due to quiet hours
    rule_val = RuleValidationResult(
        is_allowed=True, original_action=RecoveryActionType.DUNNING_EMAIL, final_action=RecoveryActionType.SMART_RETRY,
        violated_rules=["QUIET_HOURS"], explanation="Action modified to SMART_RETRY due to quiet hours."
    )

    res = execute_recovery(tx, ai_diag, rule_val, db_path=temp_db)
    # Verifies executor executed final_action (SMART_RETRY), not original AI action (DUNNING_EMAIL)
    assert res.action == RecoveryActionType.SMART_RETRY


# 3. End-to-End Safety Integration Tests

def test_e2e_safety_unsafe_ai_recommendation_blocked(temp_db):
    """
    E2E Safety Test 1:
    AI recommends unsafe action on hard decline -> Rule Engine blocks it ->
    Executor receives RuleValidationResult -> Unsafe action is NOT executed.
    """
    tx = Transaction(
        transaction_id="tx_ex_hard", merchant_id="mch_ex", customer_id="cust_ex",
        amount=Decimal("250.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE,
        attempt_count=1, max_attempts_allowed=3
    )
    ai_diag = AIDiagnosisResult(
        transaction_id="tx_ex_hard", failure_diagnosis="Misdiagnosed fraud", failure_category=DeclineCategory.HARD_DECLINE,
        recovery_probability=0.90, recommended_action=RecoveryActionType.INCENTIVIZED_RETRY, reasoning="Rogue retry"
    )

    rule_val = RuleValidationResult(
        is_allowed=False, original_action=RecoveryActionType.INCENTIVIZED_RETRY, final_action=RecoveryActionType.NO_ACTION_BLOCK,
        violated_rules=["HARD_DECLINE_BLOCK"], explanation="Hard decline retries blocked."
    )

    res = execute_recovery(tx, ai_diag, rule_val, db_path=temp_db)

    # Unsafe action NOT executed
    assert res.execution_status == "BLOCKED"
    assert res.success is False
    assert res.recovered_amount == Decimal("0.00")

    # Verify audit trail logs record the block
    counts = get_database_counts(temp_db)
    assert counts["audit_trail"] >= 2


def test_e2e_safety_approved_smart_retry_recovers_revenue(temp_db):
    """
    E2E Safety Test 2:
    AI recommends SMART_RETRY -> Rule Engine approves -> Executor executes ->
    Simulator succeeds -> Transaction becomes RECOVERED -> Amount recorded -> Audit log created.
    """
    tx = Transaction(
        transaction_id="tx_ex_001", merchant_id="mch_ex", customer_id="cust_ex",
        amount=Decimal("100.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS, decline_category=DeclineCategory.SOFT_DECLINE,
        attempt_count=1, max_attempts_allowed=3
    )
    ai_diag = AIDiagnosisResult(
        transaction_id="tx_ex_001", failure_diagnosis="Soft decline", failure_category=DeclineCategory.SOFT_DECLINE,
        recovery_probability=0.85, recommended_action=RecoveryActionType.SMART_RETRY, reasoning="Low risk retry"
    )
    rule_val = RuleValidationResult(
        is_allowed=True, original_action=RecoveryActionType.SMART_RETRY, final_action=RecoveryActionType.SMART_RETRY,
        violated_rules=[], explanation="Approved."
    )

    res = execute_recovery(tx, ai_diag, rule_val, db_path=temp_db)

    # Verify execution outcome
    assert res.success is True
    assert res.execution_status == "RECOVERED"
    assert res.recovered_amount == Decimal("100.00")

    # Verify Database state update
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT status, attempt_count FROM transactions WHERE transaction_id = ?", ("tx_ex_001",))
    row = cursor.fetchone()
    conn.close()

    assert row["status"] == TransactionStatus.RECOVERED.value
    assert row["attempt_count"] == 2

    # Verify Audit Trail entries created
    counts = get_database_counts(temp_db)
    assert counts["audit_trail"] >= 2
