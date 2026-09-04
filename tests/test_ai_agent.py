import os
import json
import pytest
import tempfile
from decimal import Decimal
from unittest.mock import patch, MagicMock
from pydantic import ValidationError
from app.core.models import (
    Merchant, Customer, Transaction, AIDiagnosisResult, TransactionStatus,
    FailureReason, DeclineCategory, RecoveryActionType
)
from app.core.database import (
    init_db, get_database_counts, insert_merchants, insert_customers, insert_transactions
)
from app.services.ai_agent import (
    diagnose_transaction, generate_deterministic_fallback, save_diagnostic_result
)
from app.services.rule_engine import validate_recovery_action, ProposedActionPayload


@pytest.fixture
def sample_transaction():
    return Transaction(
        transaction_id="tx_ai_001",
        merchant_id="mch_001",
        customer_id="cust_001",
        amount=Decimal("99.99"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        decline_category=DeclineCategory.SOFT_DECLINE,
        attempt_count=1
    )


@pytest.fixture
def sample_customer():
    return Customer(
        customer_id="cust_001",
        merchant_id="mch_001",
        name="Test User",
        email="user@test.com",
        subscription_tier="Pro",
        lifetime_value=Decimal("500.00"),
        risk_score=0.10
    )


# 1. Schema Validation Tests

def test_ai_diagnosis_schema_valid():
    diag = AIDiagnosisResult(
        transaction_id="tx_ai_001",
        failure_diagnosis="Temporary liquidity issue",
        failure_category=DeclineCategory.SOFT_DECLINE,
        recovery_probability=0.75,
        recommended_action=RecoveryActionType.SMART_RETRY,
        retry_delay_hours=48,
        customer_message_draft="Payment retry scheduled.",
        confidence_score=0.80,
        reasoning="Soft decline with low risk history.",
        is_fallback=False
    )
    assert diag.recovery_probability == 0.75
    assert diag.recommended_action == RecoveryActionType.SMART_RETRY
    assert diag.is_fallback is False


def test_ai_diagnosis_invalid_probability_range():
    with pytest.raises(ValidationError):
        AIDiagnosisResult(
            transaction_id="tx_ai_001",
            failure_diagnosis="Invalid probability",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=1.5,  # Invalid > 1.0
            recommended_action=RecoveryActionType.SMART_RETRY,
            reasoning="Test"
        )


def test_ai_diagnosis_invalid_confidence_range():
    with pytest.raises(ValidationError):
        AIDiagnosisResult(
            transaction_id="tx_ai_001",
            failure_diagnosis="Invalid confidence",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.5,
            confidence_score=-0.2,  # Invalid < 0.0
            recommended_action=RecoveryActionType.SMART_RETRY,
            reasoning="Test"
        )


def test_ai_diagnosis_invalid_action_enum():
    with pytest.raises(ValidationError):
        AIDiagnosisResult(
            transaction_id="tx_ai_001",
            failure_diagnosis="Invalid action enum",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.5,
            recommended_action="MAGIC_RETRY",  # Invalid enum value
            reasoning="Test"
        )


def test_ai_diagnosis_negative_retry_delay():
    with pytest.raises(ValidationError):
        AIDiagnosisResult(
            transaction_id="tx_ai_001",
            failure_diagnosis="Negative delay",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.5,
            recommended_action=RecoveryActionType.SMART_RETRY,
            retry_delay_hours=-10,  # Invalid < 0
            reasoning="Test"
        )


# 2. Fallback Logic Tests (Mocked - No external network calls)

def test_ai_agent_fallback_missing_api_key(sample_transaction, sample_customer):
    res = diagnose_transaction(sample_transaction, sample_customer, api_key="")
    assert res.is_fallback is True
    assert res.recommended_action == RecoveryActionType.SMART_RETRY


@patch("requests.post")
def test_ai_agent_fallback_api_http_error(mock_post, sample_transaction, sample_customer):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_post.return_value = mock_response

    res = diagnose_transaction(sample_transaction, sample_customer, api_key="dummy_key")
    assert res.is_fallback is True
    assert "Fallback" in res.failure_diagnosis


@patch("requests.post")
def test_ai_agent_fallback_malformed_json_response(mock_post, sample_transaction, sample_customer):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "INVALID JSON STRING"}]}}]
    }
    mock_post.return_value = mock_response

    res = diagnose_transaction(sample_transaction, sample_customer, api_key="dummy_key")
    assert res.is_fallback is True


@patch("requests.post")
def test_ai_agent_fallback_validation_failure(mock_post, sample_transaction, sample_customer):
    mock_response = MagicMock()
    mock_response.status_code = 200
    invalid_data = {
        "transaction_id": "tx_ai_001",
        "failure_diagnosis": "Bad probability from AI",
        "failure_category": "SOFT_DECLINE",
        "recovery_probability": 99.0,
        "recommended_action": "SMART_RETRY",
        "retry_delay_hours": 24,
        "confidence_score": 0.5,
        "reasoning": "Malformed probability"
    }
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(invalid_data)}]}}]
    }
    mock_post.return_value = mock_response

    res = diagnose_transaction(sample_transaction, sample_customer, api_key="dummy_key")
    assert res.is_fallback is True


@patch("requests.post")
def test_ai_agent_valid_gemini_response(mock_post, sample_transaction, sample_customer):
    mock_response = MagicMock()
    mock_response.status_code = 200
    valid_data = {
        "transaction_id": "tx_ai_001",
        "failure_diagnosis": "Temporary bank error analyzed by Gemini",
        "failure_category": "SOFT_DECLINE",
        "recovery_probability": 0.82,
        "recommended_action": "SMART_RETRY",
        "retry_delay_hours": 24,
        "customer_message_draft": None,
        "confidence_score": 0.90,
        "reasoning": "Bank gateway issues typically resolve within 24 hours."
    }
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(valid_data)}]}}]
    }
    mock_post.return_value = mock_response

    res = diagnose_transaction(sample_transaction, sample_customer, api_key="dummy_key")
    assert res.is_fallback is False
    assert res.recovery_probability == 0.82
    assert res.recommended_action == RecoveryActionType.SMART_RETRY


# 3. Determinism Test for Fallback Engine

def test_fallback_engine_determinism(sample_transaction, sample_customer):
    res1 = generate_deterministic_fallback(sample_transaction, sample_customer)
    res2 = generate_deterministic_fallback(sample_transaction, sample_customer)
    assert res1.recommended_action == res2.recommended_action
    assert res1.recovery_probability == res2.recovery_probability
    assert res1.is_fallback == res2.is_fallback == True


# 4. Safety Architecture Boundary Test

def test_safety_architecture_ai_is_recommendation_only(sample_transaction, sample_customer):
    """
    Verifies that an AI diagnosis recommendation is strictly advisory and must pass
    through the Rule Engine to prevent unsafe financial execution.
    """
    hard_decline_tx = Transaction(
        transaction_id="tx_hard_001", merchant_id="mch_001", customer_id="cust_001",
        amount=Decimal("500.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE
    )

    rogue_ai_recommendation = AIDiagnosisResult(
        transaction_id="tx_hard_001",
        failure_diagnosis="AI misdiagnosis",
        failure_category=DeclineCategory.HARD_DECLINE,
        recovery_probability=0.95,
        recommended_action=RecoveryActionType.INCENTIVIZED_RETRY,
        retry_delay_hours=1,
        confidence_score=0.90,
        reasoning="Rogue AI recommendation"
    )

    # Transaction state remains unchanged by AI diagnosis alone
    assert hard_decline_tx.status == TransactionStatus.FAILED

    # Rule Engine MUST intercept and block the AI recommendation
    payload = ProposedActionPayload(
        proposed_action=rogue_ai_recommendation.recommended_action,
        recovery_probability=rogue_ai_recommendation.recovery_probability,
        offered_discount_pct=30.0
    )
    rule_res = validate_recovery_action(hard_decline_tx, payload)

    assert rule_res.is_allowed is False
    assert rule_res.final_action == RecoveryActionType.NO_ACTION_BLOCK
    assert "HARD_DECLINE_BLOCK" in rule_res.violated_rules


# 5. Database Integration Test

def test_save_diagnostic_result():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        init_db(temp_db_path)
        # Create merchant, customer, transaction first to satisfy foreign keys
        mch = Merchant(merchant_id="mch_db", name="DB Shop", email="db@shop.com")
        cust = Customer(customer_id="cust_db", merchant_id="mch_db", name="DB User", email="user@db.com")
        tx = Transaction(
            transaction_id="tx_db_001", merchant_id="mch_db", customer_id="cust_db",
            amount=Decimal("49.99"), status=TransactionStatus.FAILED
        )
        insert_merchants([mch], temp_db_path)
        insert_customers([cust], temp_db_path)
        insert_transactions([tx], temp_db_path)

        diag = AIDiagnosisResult(
            transaction_id="tx_db_001",
            failure_diagnosis="Soft decline test",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.70,
            recommended_action=RecoveryActionType.SMART_RETRY,
            retry_delay_hours=24,
            confidence_score=0.80,
            reasoning="DB integration test"
        )
        record = save_diagnostic_result(diag, db_path=temp_db_path)
        assert record.transaction_id == "tx_db_001"

        counts = get_database_counts(temp_db_path)
        assert counts["diagnostics"] == 1
    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except OSError:
                pass
