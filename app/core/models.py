from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional, Any, List, Dict
from pydantic import BaseModel, Field, field_validator


def get_utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 string format."""
    return datetime.now(timezone.utc).isoformat()


def quantize_currency(val: Any) -> Decimal:
    """Quantizes numeric value to 2 decimal places using Decimal for financial precision."""
    if val is None:
        return Decimal("0.00")
    if isinstance(val, float):
        d = Decimal(str(val))
    else:
        d = Decimal(val)
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TransactionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ANALYZING = "ANALYZING"
    ACTION_RECOMMENDED = "ACTION_RECOMMENDED"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    UNRECOVERABLE = "UNRECOVERABLE"


class DeclineCategory(str, Enum):
    SOFT_DECLINE = "SOFT_DECLINE"
    HARD_DECLINE = "HARD_DECLINE"
    DATA_MISMATCH = "DATA_MISMATCH"
    NONE = "NONE"


class FailureReason(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    TEMPORARY_BANK_FAILURE = "TEMPORARY_BANK_FAILURE"
    EXPIRED_CARD = "EXPIRED_CARD"
    DO_NOT_HONOR = "DO_NOT_HONOR"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    FRAUD_STOLEN_CARD = "FRAUD_STOLEN_CARD"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    NONE = "NONE"


class RecoveryActionType(str, Enum):
    SMART_RETRY = "SMART_RETRY"
    DUNNING_EMAIL = "DUNNING_EMAIL"
    PAYMENT_LINK_SMS = "PAYMENT_LINK_SMS"
    INCENTIVIZED_RETRY = "INCENTIVIZED_RETRY"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    NO_ACTION_BLOCK = "NO_ACTION_BLOCK"


class AuditEventType(str, Enum):
    PAYMENT_FAILED = "PAYMENT_FAILED"
    RECOVERY_DETECTED = "RECOVERY_DETECTED"
    AI_DIAGNOSIS_COMPLETED = "AI_DIAGNOSIS_COMPLETED"
    RECOVERY_ACTION_RECOMMENDED = "RECOVERY_ACTION_RECOMMENDED"
    RULE_VALIDATION_COMPLETED = "RULE_VALIDATION_COMPLETED"
    RECOVERY_ACTION_BLOCKED = "RECOVERY_ACTION_BLOCKED"
    RECOVERY_ACTION_EXECUTED = "RECOVERY_ACTION_EXECUTED"
    PAYMENT_RECOVERED = "PAYMENT_RECOVERED"
    PAYMENT_SOFT_FAILED = "PAYMENT_SOFT_FAILED"
    PAYMENT_HARD_FAILED = "PAYMENT_HARD_FAILED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


# Base Model configuration
class ConfiguredBaseModel(BaseModel):
    model_config = {
        "use_enum_values": True,
        "validate_assignment": True,
        "from_attributes": True,
    }


class Merchant(ConfiguredBaseModel):
    merchant_id: str = Field(..., description="Unique merchant identifier (e.g. mch_001)")
    name: str = Field(..., min_length=1, description="Business name")
    email: str = Field(..., description="Contact email")
    currency: str = Field(default="USD", description="Base billing currency")
    created_at: str = Field(default_factory=get_utc_now_iso)
    is_active: bool = Field(default=True)


class Customer(ConfiguredBaseModel):
    customer_id: str = Field(..., description="Unique customer identifier (e.g. cust_101)")
    merchant_id: str = Field(..., description="Associated merchant ID")
    name: str = Field(..., min_length=1, description="Customer name")
    email: str = Field(..., description="Customer email")
    phone: Optional[str] = Field(default=None, description="Customer phone number")
    subscription_tier: str = Field(default="Pro", description="Basic, Pro, Enterprise")
    lifetime_value: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"), description="Lifetime value in currency units")
    risk_score: float = Field(default=0.1, ge=0.0, le=1.0, description="Risk score between 0.0 and 1.0")
    created_at: str = Field(default_factory=get_utc_now_iso)

    @field_validator("lifetime_value", mode="before")
    @classmethod
    def validate_ltv(cls, v: Any) -> Decimal:
        return quantize_currency(v)


class Transaction(ConfiguredBaseModel):
    transaction_id: str = Field(..., description="Unique transaction ID (e.g. tx_1001)")
    merchant_id: str = Field(..., description="Associated merchant ID")
    customer_id: str = Field(..., description="Associated customer ID")
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Transaction amount in currency units")
    currency: str = Field(default="USD", description="Transaction currency")
    status: TransactionStatus = Field(default=TransactionStatus.FAILED)
    failure_reason: FailureReason = Field(default=FailureReason.NONE)
    decline_category: DeclineCategory = Field(default=DeclineCategory.NONE)
    attempt_count: int = Field(default=1, ge=1, description="Number of attempts made so far")
    max_attempts_allowed: int = Field(default=3, ge=1, description="Max retry attempts allowed")
    payment_method_type: str = Field(default="credit_card", description="credit_card, debit_card, upi, net_banking")
    card_brand: Optional[str] = Field(default="Visa", description="Visa, Mastercard, Amex, Discover")
    created_at: str = Field(default_factory=get_utc_now_iso)
    updated_at: str = Field(default_factory=get_utc_now_iso)

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, v: Any) -> Decimal:
        return quantize_currency(v)


class Diagnostic(ConfiguredBaseModel):
    diagnostic_id: str = Field(..., description="Unique diagnostic ID (e.g. diag_501)")
    transaction_id: str = Field(..., description="Associated transaction ID")
    detected_root_cause: str = Field(..., description="Summary of root cause diagnosis")
    is_recoverable: bool = Field(default=True, description="Whether revenue is potentially recoverable")
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    estimated_recovery_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    recommended_action: RecoveryActionType = Field(default=RecoveryActionType.SMART_RETRY)
    recommended_delay_hours: int = Field(default=24, ge=0)
    raw_ai_reasoning: Optional[str] = Field(default=None)
    created_at: str = Field(default_factory=get_utc_now_iso)


class BusinessRule(ConfiguredBaseModel):
    rule_id: str = Field(..., description="Unique rule ID (e.g. rule_001)")
    merchant_id: str = Field(..., description="Associated merchant ID")
    rule_name: str = Field(..., description="Human readable rule name")
    rule_type: str = Field(..., description="MAX_RETRIES, HARD_DECLINE_BLOCK, MIN_PROBABILITY, MAX_DISCOUNT_PCT, QUIET_HOURS")
    parameters_json: str = Field(default="{}", description="JSON string encoded parameters")
    is_enabled: bool = Field(default=True)
    created_at: str = Field(default_factory=get_utc_now_iso)


class AuditLog(ConfiguredBaseModel):
    log_id: str = Field(..., description="Unique log entry ID (e.g. audit_901)")
    transaction_id: str = Field(..., description="Associated transaction ID")
    actor: str = Field(..., description="SYSTEM, AI_AGENT, RULE_ENGINE, SIMULATOR, MERCHANT_USER")
    action_taken: str = Field(..., description="Short summary of action / AuditEventType value")
    previous_status: Optional[str] = Field(default=None)
    new_status: Optional[str] = Field(default=None)
    details_json: Optional[str] = Field(default=None, description="Detailed event context JSON string")
    timestamp: str = Field(default_factory=get_utc_now_iso)


# Service Models

class DetectionResult(ConfiguredBaseModel):
    transaction_id: str = Field(..., description="Transaction ID analyzed")
    is_recoverable: bool = Field(..., description="Whether revenue is potentially recoverable")
    decline_category: DeclineCategory = Field(..., description="Classified decline category")
    reason: FailureReason = Field(..., description="Specific failure reason code")
    recommended_next_step: str = Field(..., description="Deterministic next step recommendation")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional context metadata")


class ProposedActionPayload(ConfiguredBaseModel):
    proposed_action: RecoveryActionType = Field(..., description="Proposed recovery action")
    recovery_probability: float = Field(default=0.5, ge=0.0, le=1.0, description="Estimated recovery probability score")
    offered_discount_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Offered discount percentage")
    current_hour_utc: Optional[int] = Field(default=None, ge=0, le=23, description="Current hour UTC (0-23) for quiet hours validation")


class RuleValidationResult(ConfiguredBaseModel):
    is_allowed: bool = Field(..., description="True if action complies with all rules (or was modified safely)")
    original_action: RecoveryActionType = Field(..., description="Action originally proposed before rule engine")
    final_action: RecoveryActionType = Field(..., description="Final action after rule evaluation (allowed, modified, or blocked)")
    modified_discount_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Final approved discount percentage")
    violated_rules: List[str] = Field(default_factory=list, description="List of rule types/names violated")
    explanation: str = Field(..., description="Human-readable decision explanation")
    audit_event_details: Dict[str, Any] = Field(default_factory=dict, description="Structured log context ready for audit trail")


class AIDiagnosisResult(ConfiguredBaseModel):
    transaction_id: str = Field(..., description="ID of analyzed transaction")
    failure_diagnosis: str = Field(..., description="AI diagnosis of root cause")
    failure_category: DeclineCategory = Field(..., description="Decline category code")
    recovery_probability: float = Field(..., ge=0.0, le=1.0, description="Estimated recovery probability (0.0 to 1.0)")
    recommended_action: RecoveryActionType = Field(..., description="Recommended recovery action from RecoveryActionType enum")
    retry_delay_hours: int = Field(default=24, ge=0, description="Recommended retry delay in hours (>= 0)")
    customer_message_draft: Optional[str] = Field(default=None, description="Draft outreach message for customer communication")
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0, description="AI confidence score (0.0 to 1.0)")
    reasoning: str = Field(..., description="Detailed AI reasoning behind recommendation")
    is_fallback: bool = Field(default=False, description="True if result was generated by deterministic fallback engine")
    created_at: str = Field(default_factory=get_utc_now_iso)


class ExecutionResult(ConfiguredBaseModel):
    transaction_id: str = Field(..., description="Transaction ID executed")
    action: RecoveryActionType = Field(..., description="Recovery action attempted")
    execution_status: str = Field(..., description="EXECUTED, RECOVERED, SOFT_FAILED, HARD_FAILED, BLOCKED, MANUAL_REVIEW, COMMUNICATION_SENT")
    success: bool = Field(..., description="True if transaction revenue was successfully recovered")
    recovered_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"), description="Amount of revenue successfully recovered")
    gateway_response_code: str = Field(default="200_OK", description="Simulated gateway response code")
    execution_time_ms: int = Field(default=120, ge=0, description="Simulated execution latency in milliseconds")
    message: str = Field(..., description="Detailed execution log message")
    timestamp: str = Field(default_factory=get_utc_now_iso)

    @field_validator("recovered_amount", mode="before")
    @classmethod
    def validate_rec_amount(cls, v: Any) -> Decimal:
        return quantize_currency(v)


class BatchRecoverySummary(ConfiguredBaseModel):
    total_transactions_analyzed: int = Field(..., ge=0)
    total_failed_transactions: int = Field(default=0, ge=0)
    recoverable_transactions: int = Field(..., ge=0)
    unrecoverable_transactions: int = Field(..., ge=0)
    recovery_attempts: int = Field(..., ge=0)
    successful_recoveries: int = Field(..., ge=0)
    failed_attempts: int = Field(..., ge=0)
    blocked_actions: int = Field(..., ge=0)
    total_failed_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    potentially_recoverable_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    recovered_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    recoverable_transaction_recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="successful_recoveries / recoverable_transactions * 100")
    overall_failed_transaction_recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="successful_recoveries / total_failed_transactions * 100")
    transaction_recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Deprecated alias for recoverable_transaction_recovery_rate_pct")
    revenue_recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="recovered_revenue / potentially_recoverable_revenue * 100")
    average_recovered_transaction_value: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))

    @field_validator("total_failed_revenue", "potentially_recoverable_revenue", "recovered_revenue", "average_recovered_transaction_value", mode="before")
    @classmethod
    def validate_totals(cls, v: Any) -> Decimal:
        return quantize_currency(v)


# Phase 5 Analytics & Evaluation Breakdown Models

class RevenueBreakdownItem(ConfiguredBaseModel):
    category_key: str = Field(...)
    transaction_count: int = Field(default=0, ge=0)
    failed_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    recoverable_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    recovered_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    revenue_recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)

    @field_validator("failed_revenue", "recoverable_revenue", "recovered_revenue", mode="before")
    @classmethod
    def validate_item_cur(cls, v: Any) -> Decimal:
        return quantize_currency(v)


class ActionPerformanceItem(ConfiguredBaseModel):
    action: str = Field(...)
    number_recommended: int = Field(default=0, ge=0)
    number_approved: int = Field(default=0, ge=0)
    number_blocked: int = Field(default=0, ge=0)
    number_executed: int = Field(default=0, ge=0)
    successful_recoveries: int = Field(default=0, ge=0)
    recovered_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)

    @field_validator("recovered_revenue", mode="before")
    @classmethod
    def validate_act_cur(cls, v: Any) -> Decimal:
        return quantize_currency(v)


class CalibrationBucket(ConfiguredBaseModel):
    bucket_label: str = Field(...)  # e.g., "0-20%", "20-40%"
    min_prob: float = Field(..., ge=0.0, le=1.0)
    max_prob: float = Field(..., ge=0.0, le=1.0)
    prediction_count: int = Field(default=0, ge=0)
    avg_predicted_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    actual_recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0)


class EvaluationMetrics(ConfiguredBaseModel):
    total_predictions: int = Field(default=0, ge=0)
    ai_prediction_population_description: str = Field(default="All evaluated failed transactions")
    avg_predicted_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    ai_prediction_outcome_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="actual_recovered_count / total_predictions * 100")
    actual_recovery_rate_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Alias for ai_prediction_outcome_rate_pct")
    mean_absolute_error: float = Field(default=0.0, ge=0.0, le=1.0)
    calibration_buckets: List[CalibrationBucket] = Field(default_factory=list)
    gemini_diagnosis_count: int = Field(default=0, ge=0)
    fallback_diagnosis_count: int = Field(default=0, ge=0)
    gemini_recovered_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    fallback_recovered_revenue: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))

    @field_validator("gemini_recovered_revenue", "fallback_recovered_revenue", mode="before")
    @classmethod
    def validate_eval_cur(cls, v: Any) -> Decimal:
        return quantize_currency(v)


class SafetyMetrics(ConfiguredBaseModel):
    total_ai_recommendations: int = Field(default=0, ge=0)
    approved_recommendations: int = Field(default=0, ge=0)
    modified_recommendations: int = Field(default=0, ge=0)
    blocked_recommendations: int = Field(default=0, ge=0)
    pct_blocked: float = Field(default=0.0, ge=0.0, le=100.0)
    pct_modified: float = Field(default=0.0, ge=0.0, le=100.0)
    rule_violation_frequency: Dict[str, int] = Field(default_factory=dict, description="Non-mutually-exclusive rule violation counts")
