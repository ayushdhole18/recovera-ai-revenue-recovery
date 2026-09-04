import pytest
from decimal import Decimal
from app.core.models import (
    Transaction, TransactionStatus, FailureReason,
    DeclineCategory, DetectionResult
)
from app.services.detector import detect_recoverability, detect_batch


def test_detector_insufficient_funds_recoverable():
    tx = Transaction(
        transaction_id="tx_det_001",
        merchant_id="mch_001",
        customer_id="cust_001",
        amount=Decimal("49.99"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        decline_category=DeclineCategory.SOFT_DECLINE
    )
    result = detect_recoverability(tx)
    assert isinstance(result, DetectionResult)
    assert result.is_recoverable is True
    assert result.decline_category == DeclineCategory.SOFT_DECLINE
    assert result.reason == FailureReason.INSUFFICIENT_FUNDS
    assert "retry" in result.recommended_next_step.lower() or "dunning" in result.recommended_next_step.lower()


def test_detector_temporary_bank_failure_recoverable():
    tx = Transaction(
        transaction_id="tx_det_002",
        merchant_id="mch_001",
        customer_id="cust_002",
        amount=Decimal("199.00"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.TEMPORARY_BANK_FAILURE,
        decline_category=DeclineCategory.SOFT_DECLINE
    )
    result = detect_recoverability(tx)
    assert result.is_recoverable is True
    assert result.decline_category == DeclineCategory.SOFT_DECLINE
    assert result.reason == FailureReason.TEMPORARY_BANK_FAILURE


def test_detector_expired_card_data_mismatch():
    tx = Transaction(
        transaction_id="tx_det_003",
        merchant_id="mch_001",
        customer_id="cust_003",
        amount=Decimal("29.99"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.EXPIRED_CARD,
        decline_category=DeclineCategory.DATA_MISMATCH
    )
    result = detect_recoverability(tx)
    assert result.is_recoverable is True
    assert result.decline_category == DeclineCategory.DATA_MISMATCH
    assert result.reason == FailureReason.EXPIRED_CARD
    assert "payment method update" in result.recommended_next_step.lower()


def test_detector_fraud_stolen_card_hard_decline():
    tx = Transaction(
        transaction_id="tx_det_004",
        merchant_id="mch_001",
        customer_id="cust_004",
        amount=Decimal("500.00"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD,
        decline_category=DeclineCategory.HARD_DECLINE
    )
    result = detect_recoverability(tx)
    assert result.is_recoverable is False
    assert result.decline_category == DeclineCategory.HARD_DECLINE
    assert result.reason == FailureReason.FRAUD_STOLEN_CARD
    assert "block" in result.recommended_next_step.lower()


def test_detector_account_closed_hard_decline():
    tx = Transaction(
        transaction_id="tx_det_005",
        merchant_id="mch_001",
        customer_id="cust_005",
        amount=Decimal("89.00"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.ACCOUNT_CLOSED,
        decline_category=DeclineCategory.HARD_DECLINE
    )
    result = detect_recoverability(tx)
    assert result.is_recoverable is False
    assert result.decline_category == DeclineCategory.HARD_DECLINE
    assert result.reason == FailureReason.ACCOUNT_CLOSED


def test_detector_successful_transaction_not_recoverable():
    tx = Transaction(
        transaction_id="tx_det_006",
        merchant_id="mch_001",
        customer_id="cust_006",
        amount=Decimal("99.00"),
        status=TransactionStatus.SUCCESS,
        failure_reason=FailureReason.NONE,
        decline_category=DeclineCategory.NONE
    )
    result = detect_recoverability(tx)
    assert result.is_recoverable is False
    assert result.decline_category == DeclineCategory.NONE
    assert "successful" in result.recommended_next_step.lower()


def test_detector_batch_processing():
    txs = [
        Transaction(
            transaction_id="tx_batch_1", merchant_id="mch_1", customer_id="c_1",
            amount=Decimal("10.00"), status=TransactionStatus.FAILED,
            failure_reason=FailureReason.INSUFFICIENT_FUNDS, decline_category=DeclineCategory.SOFT_DECLINE
        ),
        Transaction(
            transaction_id="tx_batch_2", merchant_id="mch_1", customer_id="c_2",
            amount=Decimal("20.00"), status=TransactionStatus.FAILED,
            failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE
        )
    ]
    results = detect_batch(txs)
    assert len(results) == 2
    assert results[0].is_recoverable is True
    assert results[1].is_recoverable is False
