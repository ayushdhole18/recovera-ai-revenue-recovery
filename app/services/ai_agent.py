import os
import json
import logging
import requests
from typing import Optional, Dict, Any
from app.config import GEMINI_API_KEY, DATABASE_PATH
from app.core.models import (
    Transaction, Customer, AIDiagnosisResult, Diagnostic,
    DeclineCategory, FailureReason, RecoveryActionType
)
from app.core.database import insert_diagnostics
from app.services.prompts import SYSTEM_INSTRUCTION, build_diagnostic_user_prompt

logger = logging.getLogger(__name__)


def generate_deterministic_fallback(
    transaction: Transaction,
    customer: Optional[Customer] = None
) -> AIDiagnosisResult:
    """
    Generates a deterministic diagnosis result when Gemini API is unconfigured,
    unavailable, times out, or returns invalid outputs.
    """
    reason = str(transaction.failure_reason).upper()
    category = str(transaction.decline_category).upper()

    if reason in [FailureReason.FRAUD_STOLEN_CARD.value, FailureReason.ACCOUNT_CLOSED.value] or category == DeclineCategory.HARD_DECLINE.value:
        return AIDiagnosisResult(
            transaction_id=transaction.transaction_id,
            failure_diagnosis="Permanent hard decline detected (Deterministic Fallback)",
            failure_category=DeclineCategory.HARD_DECLINE,
            recovery_probability=0.0,
            recommended_action=RecoveryActionType.NO_ACTION_BLOCK,
            retry_delay_hours=0,
            customer_message_draft=None,
            confidence_score=0.95,
            reasoning="Fallback Engine: Hard declines (fraud/closed account) cannot be safely recovered.",
            is_fallback=True
        )

    elif reason in [FailureReason.EXPIRED_CARD.value, FailureReason.AUTHENTICATION_FAILURE.value] or category == DeclineCategory.DATA_MISMATCH.value:
        return AIDiagnosisResult(
            transaction_id=transaction.transaction_id,
            failure_diagnosis="Payment card expired or authentication mismatch (Deterministic Fallback)",
            failure_category=DeclineCategory.DATA_MISMATCH,
            recovery_probability=0.60,
            recommended_action=RecoveryActionType.PAYMENT_LINK_SMS,
            retry_delay_hours=0,
            customer_message_draft="Your payment method needs an update. Please use the secure link to refresh your card details.",
            confidence_score=0.80,
            reasoning="Fallback Engine: Data mismatch requires customer card update link.",
            is_fallback=True
        )

    elif reason == FailureReason.TEMPORARY_BANK_FAILURE.value:
        return AIDiagnosisResult(
            transaction_id=transaction.transaction_id,
            failure_diagnosis="Transient bank gateway error (Deterministic Fallback)",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.80,
            recommended_action=RecoveryActionType.SMART_RETRY,
            retry_delay_hours=24,
            customer_message_draft=None,
            confidence_score=0.85,
            reasoning="Fallback Engine: Temporary bank errors resolve quickly via background retries.",
            is_fallback=True
        )

    elif reason == FailureReason.INSUFFICIENT_FUNDS.value:
        return AIDiagnosisResult(
            transaction_id=transaction.transaction_id,
            failure_diagnosis="Temporary liquidity insufficiency (Deterministic Fallback)",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.65,
            recommended_action=RecoveryActionType.SMART_RETRY,
            retry_delay_hours=48,
            customer_message_draft="Your payment was declined due to temporary funds availability. We will re-attempt automatically in 48 hours.",
            confidence_score=0.75,
            reasoning="Fallback Engine: Insufficient funds recovered via timed smart retry window.",
            is_fallback=True
        )

    else:
        return AIDiagnosisResult(
            transaction_id=transaction.transaction_id,
            failure_diagnosis="Unclassified soft decline (Deterministic Fallback)",
            failure_category=DeclineCategory.SOFT_DECLINE,
            recovery_probability=0.50,
            recommended_action=RecoveryActionType.MANUAL_REVIEW,
            retry_delay_hours=24,
            customer_message_draft=None,
            confidence_score=0.50,
            reasoning="Fallback Engine: Defaulting to manual review for unclassified failure reason.",
            is_fallback=True
        )


def diagnose_transaction(
    transaction: Transaction,
    customer: Optional[Customer] = None,
    history_summary: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None
) -> AIDiagnosisResult:
    """
    Sends structured transaction context to Gemini API to request JSON diagnosis.
    If API key is missing or an error occurs, falls back gracefully to deterministic diagnosis.
    """
    effective_api_key = api_key or GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")

    # Fallback if API key is not configured
    if not effective_api_key or effective_api_key.strip() == "" or effective_api_key == "your_gemini_api_key_here":
        logger.info("GEMINI_API_KEY missing or default. Using deterministic fallback engine.")
        return generate_deterministic_fallback(transaction, customer)

    user_prompt = build_diagnostic_user_prompt(transaction, customer, history_summary)

    # Gemini REST API endpoint
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={effective_api_key}"
    headers = {"Content-Type": "application/json"}

    payload = {
        "system_instruction": {
            "parts": [{"text": SYSTEM_INSTRUCTION}]
        },
        "contents": [
            {"parts": [{"text": user_prompt}]}
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.2
        }
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
        if response.status_code != 200:
            logger.warning(f"Gemini API returned status code {response.status_code}. Using fallback.")
            return generate_deterministic_fallback(transaction, customer)

        res_json = response.json()

        # Extract text response from Gemini output structure
        try:
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            logger.warning("Gemini response structure missing content parts. Using fallback.")
            return generate_deterministic_fallback(transaction, customer)

        # Parse JSON content
        parsed_dict = json.loads(raw_text)

        # Validate with Pydantic model
        diagnosis = AIDiagnosisResult(**parsed_dict)
        diagnosis.is_fallback = False
        return diagnosis

    except (requests.RequestException, json.JSONDecodeError, Exception) as err:
        logger.warning(f"Error invoking Gemini API or parsing response ({err}). Using fallback.")
        return generate_deterministic_fallback(transaction, customer)


def save_diagnostic_result(
    diagnosis: AIDiagnosisResult,
    db_path: str = DATABASE_PATH
) -> Diagnostic:
    """
    Saves an AIDiagnosisResult into the SQLite diagnostics database table.
    """
    diagnostic_record = Diagnostic(
        diagnostic_id=f"diag_{diagnosis.transaction_id}",
        transaction_id=diagnosis.transaction_id,
        detected_root_cause=diagnosis.failure_diagnosis,
        is_recoverable=diagnosis.recommended_action != RecoveryActionType.NO_ACTION_BLOCK,
        confidence_score=diagnosis.confidence_score,
        estimated_recovery_probability=diagnosis.recovery_probability,
        recommended_action=diagnosis.recommended_action,
        recommended_delay_hours=diagnosis.retry_delay_hours,
        raw_ai_reasoning=diagnosis.reasoning,
        created_at=diagnosis.created_at
    )

    insert_diagnostics([diagnostic_record], db_path)
    return diagnostic_record


if __name__ == "__main__":
    from decimal import Decimal
    from app.core.models import TransactionStatus

    print("=== Recovera AI - Manual Developer Gemini Test CLI ===")
    sample_tx = Transaction(
        transaction_id="tx_manual_test_901",
        merchant_id="mch_001",
        customer_id="cust_001",
        amount=Decimal("149.99"),
        status=TransactionStatus.FAILED,
        failure_reason=FailureReason.INSUFFICIENT_FUNDS,
        decline_category=DeclineCategory.SOFT_DECLINE,
        attempt_count=1
    )
    sample_cust = Customer(
        customer_id="cust_001",
        merchant_id="mch_001",
        name="Alex Smith",
        email="alex@example.com",
        subscription_tier="Pro",
        lifetime_value=Decimal("890.00"),
        risk_score=0.12
    )

    result = diagnose_transaction(sample_tx, sample_cust)
    print(f"Transaction ID       : {result.transaction_id}")
    print(f"Engine Used          : {'Deterministic Fallback' if result.is_fallback else 'Gemini 2.5 Flash AI'}")
    print(f"Failure Diagnosis    : {result.failure_diagnosis}")
    print(f"Recovery Probability : {result.recovery_probability:.2f}")
    print(f"Recommended Action   : {result.recommended_action}")
    print(f"Retry Delay Hours    : {result.retry_delay_hours} hrs")
    print(f"Confidence Score     : {result.confidence_score:.2f}")
    print(f"Customer Message     : {result.customer_message_draft or 'None'}")
    print(f"Reasoning            : {result.reasoning}")
