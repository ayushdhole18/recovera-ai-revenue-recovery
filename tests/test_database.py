import os
import sqlite3
import tempfile
import pytest
from decimal import Decimal
from app.core.database import (
    init_db, reset_db, get_database_counts, get_connection,
    insert_merchants, insert_customers, insert_transactions, insert_audit_logs
)
from app.core.models import (
    Merchant, Customer, Transaction, AuditLog, TransactionStatus,
    FailureReason, DeclineCategory
)
from app.core.seed_data import seed_database


@pytest.fixture
def temp_db():
    """Provides a temporary SQLite database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    init_db(temp_db_path)
    yield temp_db_path

    if os.path.exists(temp_db_path):
        try:
            os.remove(temp_db_path)
        except OSError:
            pass


def test_init_db_creates_tables(temp_db):
    counts = get_database_counts(temp_db)
    for table, count in counts.items():
        assert count == 0


def test_insert_and_query_records(temp_db):
    mch = Merchant(
        merchant_id="mch_test",
        name="Test Shop",
        email="test@shop.com"
    )
    insert_merchants([mch], temp_db)

    cust = Customer(
        customer_id="cust_test",
        merchant_id="mch_test",
        name="Alice Smith",
        email="alice@test.com",
        lifetime_value=Decimal("150.75")
    )
    insert_customers([cust], temp_db)

    tx = Transaction(
        transaction_id="tx_test",
        merchant_id="mch_test",
        customer_id="cust_test",
        amount=Decimal("49.99"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        decline_category=DeclineCategory.SOFT_DECLINE
    )
    insert_transactions([tx], temp_db)

    counts = get_database_counts(temp_db)
    assert counts["merchants"] == 1
    assert counts["customers"] == 1
    assert counts["transactions"] == 1


def test_audit_trail_append_only_contract(temp_db):
    """Verifies that audit trail records can be inserted, but UPDATE and DELETE are blocked by database triggers."""
    mch = Merchant(merchant_id="mch_test", name="Test Shop", email="test@shop.com")
    insert_merchants([mch], temp_db)

    cust = Customer(customer_id="cust_test", merchant_id="mch_test", name="Alice", email="alice@test.com")
    insert_customers([cust], temp_db)

    tx = Transaction(
        transaction_id="tx_test", merchant_id="mch_test", customer_id="cust_test",
        amount=Decimal("29.99"), status=TransactionStatus.FAILED
    )
    insert_transactions([tx], temp_db)

    log = AuditLog(
        log_id="audit_101",
        transaction_id="tx_test",
        actor="SYSTEM",
        action_taken="PAYMENT_FAILED_DETECTED",
        previous_status=None,
        new_status="FAILED"
    )

    # 1. INSERT must succeed
    insert_audit_logs([log], temp_db)
    counts = get_database_counts(temp_db)
    assert counts["audit_trail"] == 1

    conn = get_connection(temp_db)
    cursor = conn.cursor()

    try:
        # 2. UPDATE operation must be rejected by trigger (raises IntegrityError or OperationalError)
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)) as exc_info:
            cursor.execute("UPDATE audit_trail SET action_taken = 'MUTATED' WHERE log_id = 'audit_101'")
        assert "append-only" in str(exc_info.value) or "prohibited" in str(exc_info.value)

        # 3. DELETE operation must be rejected by trigger
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)) as exc_info:
            cursor.execute("DELETE FROM audit_trail WHERE log_id = 'audit_101'")
        assert "append-only" in str(exc_info.value) or "prohibited" in str(exc_info.value)
    finally:
        conn.close()


def test_seed_database_functionality(temp_db):
    counts = seed_database(temp_db, seed_val=123)
    assert counts["merchants"] == 10
    assert counts["customers"] >= 200
    assert counts["transactions"] >= 1000
    assert counts["business_rules"] >= 40
    assert counts["audit_trail"] > 0
