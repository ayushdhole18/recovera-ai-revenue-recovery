import pytest
import json
from decimal import Decimal
from app.core.models import (
    Transaction, BusinessRule, ProposedActionPayload,
    RuleValidationResult, RecoveryActionType, TransactionStatus,
    FailureReason, DeclineCategory
)
from app.services.rule_engine import validate_recovery_action, is_hour_in_quiet_window


@pytest.fixture
def sample_merchant_rules():
    return [
        BusinessRule(
            rule_id="r1", merchant_id="mch_001", rule_name="Max Retries", rule_type="MAX_RETRIES",
            parameters_json=json.dumps({"max_retries": 3})
        ),
        BusinessRule(
            rule_id="r2", merchant_id="mch_001", rule_name="Block Hard Declines", rule_type="HARD_DECLINE_BLOCK",
            parameters_json=json.dumps({"allow_stolen_card_retry": False})
        ),
        BusinessRule(
            rule_id="r3", merchant_id="mch_001", rule_name="Min Probability", rule_type="MIN_PROBABILITY",
            parameters_json=json.dumps({"min_probability": 0.15})
        ),
        BusinessRule(
            rule_id="r4", merchant_id="mch_001", rule_name="Max Discount", rule_type="MAX_DISCOUNT_PCT",
            parameters_json=json.dumps({"max_discount_pct": 20.0})
        ),
        BusinessRule(
            rule_id="r5", merchant_id="mch_001", rule_name="Quiet Hours", rule_type="QUIET_HOURS",
            parameters_json=json.dumps({"quiet_hours_start": 22, "quiet_hours_end": 6})
        )
    ]


def test_rule_retry_within_allowed_count(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_1", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED, attempt_count=2, max_attempts_allowed=3
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.SMART_RETRY,
        recovery_probability=0.80,
        offered_discount_pct=0.0
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is True
    assert res.final_action == RecoveryActionType.SMART_RETRY
    assert len(res.violated_rules) == 0


def test_rule_retry_exceeding_max_count(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_2", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED, attempt_count=3, max_attempts_allowed=3
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.SMART_RETRY,
        recovery_probability=0.80
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is False
    assert res.final_action == RecoveryActionType.NO_ACTION_BLOCK
    assert "MAX_RETRY_COUNT" in res.violated_rules


def test_rule_hard_decline_blocked(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_3", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("100.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.SMART_RETRY,
        recovery_probability=0.75
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is False
    assert res.final_action == RecoveryActionType.NO_ACTION_BLOCK
    assert "HARD_DECLINE_BLOCK" in res.violated_rules


def test_rule_low_recovery_probability_blocked(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_4", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.DUNNING_EMAIL,
        recovery_probability=0.05  # below 0.15 threshold
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is False
    assert res.final_action == RecoveryActionType.NO_ACTION_BLOCK
    assert "MIN_PROBABILITY" in res.violated_rules


def test_rule_discount_within_limit_allowed(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_5", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.INCENTIVIZED_RETRY,
        recovery_probability=0.60,
        offered_discount_pct=15.0  # cap is 20.0
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is True
    assert res.modified_discount_pct == 15.0


def test_rule_discount_above_limit_capped(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_6", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.INCENTIVIZED_RETRY,
        recovery_probability=0.60,
        offered_discount_pct=35.0  # exceeds 20.0 cap
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is True
    assert res.modified_discount_pct == 20.0
    assert "MAX_DISCOUNT_PCT" in res.violated_rules


def test_rule_action_during_quiet_hours_modified(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_7", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.DUNNING_EMAIL,
        recovery_probability=0.70,
        current_hour_utc=23  # within 22 to 6 quiet hours
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is True
    assert res.final_action == RecoveryActionType.SMART_RETRY  # shifted to silent retry
    assert "QUIET_HOURS" in res.violated_rules


def test_rule_action_outside_quiet_hours_allowed(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_8", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.DUNNING_EMAIL,
        recovery_probability=0.70,
        current_hour_utc=14  # outside quiet hours
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is True
    assert res.final_action == RecoveryActionType.DUNNING_EMAIL
    assert len(res.violated_rules) == 0


def test_rule_already_recovered_transaction_blocked(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_9", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.RECOVERED, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.SMART_RETRY,
        recovery_probability=0.90
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is False
    assert res.final_action == RecoveryActionType.NO_ACTION_BLOCK
    assert "ALREADY_RECOVERED" in res.violated_rules


def test_rule_multiple_rule_violations_returned(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_r_10", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("50.00"), status=TransactionStatus.FAILED,
        failure_reason=FailureReason.FRAUD_STOLEN_CARD, decline_category=DeclineCategory.HARD_DECLINE, attempt_count=3
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.INCENTIVIZED_RETRY,
        recovery_probability=0.05,  # low prob
        offered_discount_pct=40.0   # high discount
    )
    res = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    assert res.is_allowed is False
    assert res.final_action == RecoveryActionType.NO_ACTION_BLOCK
    assert "HARD_DECLINE_BLOCK" in res.violated_rules
    assert "MAX_RETRY_COUNT" in res.violated_rules
    assert "MIN_PROBABILITY" in res.violated_rules
    assert "MAX_DISCOUNT_PCT" in res.violated_rules


def test_rule_engine_determinism(sample_merchant_rules):
    tx = Transaction(
        transaction_id="tx_det_test", merchant_id="mch_001", customer_id="c_1",
        amount=Decimal("99.99"), status=TransactionStatus.FAILED, attempt_count=1
    )
    payload = ProposedActionPayload(
        proposed_action=RecoveryActionType.DUNNING_EMAIL,
        recovery_probability=0.75,
        current_hour_utc=10
    )

    res1 = validate_recovery_action(tx, payload, rules=sample_merchant_rules)
    res2 = validate_recovery_action(tx, payload, rules=sample_merchant_rules)

    # Identical inputs must yield identical outputs
    assert res1.is_allowed == res2.is_allowed
    assert res1.final_action == res2.final_action
    assert res1.modified_discount_pct == res2.modified_discount_pct
    assert res1.violated_rules == res2.violated_rules
    assert res1.explanation == res2.explanation
    assert res1.audit_event_details == res2.audit_event_details


def test_is_hour_in_quiet_window():
    # 22 to 6 quiet hours window
    assert is_hour_in_quiet_window(23, 22, 6) is True
    assert is_hour_in_quiet_window(2, 22, 6) is True
    assert is_hour_in_quiet_window(12, 22, 6) is False
