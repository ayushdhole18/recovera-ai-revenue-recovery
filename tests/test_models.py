import pytest
from decimal import Decimal
from pydantic import ValidationError
from app.core.models import (
    Merchant, Customer, Transaction, Diagnostic, BusinessRule, AuditLog,
    TransactionStatus, FailureReason, DeclineCategory, RecoveryActionType,
    quantize_currency
)


def test_merchant_model_valid():
    merchant = Merchant(
        merchant_id="mch_999",
        name="Test Merchant",
        email="billing@test.com",
        currency="USD"
    )
    assert merchant.merchant_id == "mch_999"
    assert merchant.name == "Test Merchant"
    assert merchant.is_active is True


def test_customer_model_decimal_precision():
    cust = Customer(
        customer_id="cust_999",
        merchant_id="mch_999",
        name="John Doe",
        email="john@example.com",
        lifetime_value=150.4567,
        risk_score=0.25
    )
    # LTV should be converted to Decimal and quantized to 2 decimal places
    assert isinstance(cust.lifetime_value, Decimal)
    assert cust.lifetime_value == Decimal("150.46")
    assert cust.risk_score == 0.25


def test_transaction_model_decimal_precision():
    tx = Transaction(
        transaction_id="tx_9999",
        merchant_id="mch_999",
        customer_id="cust_999",
        amount=99.999,
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        decline_category=DeclineCategory.SOFT_DECLINE
    )
    assert isinstance(tx.amount, Decimal)
    assert tx.amount == Decimal("100.00")
    assert tx.status == TransactionStatus.FAILED
    assert tx.decline_category == DeclineCategory.SOFT_DECLINE


def test_monetary_exact_arithmetic_without_float_rounding_errors():
    # Floating-point arithmetic error demonstration: 0.1 + 0.2 == 0.30000000000000004
    # With quantize_currency and Decimal, calculations maintain exact 2-decimal precision
    amt1 = quantize_currency(0.10)
    amt2 = quantize_currency(0.20)
    total = amt1 + amt2
    assert total == Decimal("0.30")
    assert str(total) == "0.30"

    # Multi-item sum test
    items = [Decimal("10.01"), Decimal("20.02"), Decimal("30.03")]
    assert sum(items) == Decimal("60.06")


def test_customer_invalid_risk_score():
    with pytest.raises(ValidationError):
        Customer(
            customer_id="cust_999",
            merchant_id="mch_999",
            name="John Doe",
            email="john@example.com",
            risk_score=1.5  # invalid > 1.0
        )


def test_transaction_invalid_amount():
    with pytest.raises(ValidationError):
        Transaction(
            transaction_id="tx_9999",
            merchant_id="mch_999",
            customer_id="cust_999",
            amount=-10.0  # invalid <= 0
        )


def test_diagnostic_model_valid():
    diag = Diagnostic(
        diagnostic_id="diag_999",
        transaction_id="tx_9999",
        detected_root_cause="Temporary insufficient funds",
        confidence_score=0.85,
        estimated_recovery_probability=0.72,
        recommended_action=RecoveryActionType.SMART_RETRY,
        recommended_delay_hours=48
    )
    assert diag.diagnostic_id == "diag_999"
    assert diag.is_recoverable is True
    assert diag.recommended_action == RecoveryActionType.SMART_RETRY


def test_business_rule_model_valid():
    rule = BusinessRule(
        rule_id="rule_999",
        merchant_id="mch_999",
        rule_name="Max Retries",
        rule_type="MAX_RETRIES",
        parameters_json='{"max_retries": 3}'
    )
    assert rule.rule_id == "rule_999"
    assert rule.is_enabled is True


def test_audit_log_model_valid():
    log = AuditLog(
        log_id="audit_999",
        transaction_id="tx_9999",
        actor="SYSTEM",
        action_taken="PAYMENT_FAILED",
        previous_status=None,
        new_status="FAILED"
    )
    assert log.log_id == "audit_999"
    assert log.actor == "SYSTEM"
