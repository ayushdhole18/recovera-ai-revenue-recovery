from typing import List
from app.core.models import (
    Transaction, DetectionResult, TransactionStatus,
    FailureReason, DeclineCategory
)


def detect_recoverability(transaction: Transaction) -> DetectionResult:
    """
    Analyzes a payment transaction using deterministic rules to classify
    decline types and determine if revenue recovery is possible.

    No AI or external APIs are invoked in this layer.
    """
    status = str(transaction.status).upper()
    reason = str(transaction.failure_reason).upper()
    category = str(transaction.decline_category).upper()

    # 1. Already successful or recovered transactions are not recoverable
    if status in [TransactionStatus.SUCCESS.value, TransactionStatus.RECOVERED.value]:
        return DetectionResult(
            transaction_id=transaction.transaction_id,
            is_recoverable=False,
            decline_category=DeclineCategory.NONE,
            reason=FailureReason.NONE,
            recommended_next_step="No action required - transaction already successful",
            details={
                "merchant_id": transaction.merchant_id,
                "customer_id": transaction.customer_id,
                "status": status,
                "amount": float(transaction.amount)
            }
        )

    # 2. Hard Declines: Stolen card, fraud, closed account
    if (
        reason in [FailureReason.FRAUD_STOLEN_CARD.value, FailureReason.ACCOUNT_CLOSED.value]
        or category == DeclineCategory.HARD_DECLINE.value
    ):
        return DetectionResult(
            transaction_id=transaction.transaction_id,
            is_recoverable=False,
            decline_category=DeclineCategory.HARD_DECLINE,
            reason=transaction.failure_reason,
            recommended_next_step="Block further retries - permanent decline",
            details={
                "merchant_id": transaction.merchant_id,
                "customer_id": transaction.customer_id,
                "attempt_count": transaction.attempt_count,
                "card_brand": transaction.card_brand
            }
        )

    # 3. Data Mismatches: Expired card, authentication failure requiring customer action
    if (
        reason in [FailureReason.EXPIRED_CARD.value, FailureReason.AUTHENTICATION_FAILURE.value]
        or category == DeclineCategory.DATA_MISMATCH.value
    ):
        return DetectionResult(
            transaction_id=transaction.transaction_id,
            is_recoverable=True,
            decline_category=DeclineCategory.DATA_MISMATCH,
            reason=transaction.failure_reason,
            recommended_next_step="Request customer payment method update or re-authentication",
            details={
                "merchant_id": transaction.merchant_id,
                "customer_id": transaction.customer_id,
                "attempt_count": transaction.attempt_count,
                "requires_customer_interaction": True
            }
        )

    # 4. Soft Declines: Insufficient funds, temporary bank failure, do not honor
    # Default for all other recoverable failures
    actual_category = (
        DeclineCategory.SOFT_DECLINE
        if category in [DeclineCategory.SOFT_DECLINE.value, DeclineCategory.NONE.value]
        else DeclineCategory(category)
    )

    return DetectionResult(
        transaction_id=transaction.transaction_id,
        is_recoverable=True,
        decline_category=actual_category,
        reason=transaction.failure_reason,
        recommended_next_step="Schedule smart retry or send dunning notification",
        details={
            "merchant_id": transaction.merchant_id,
            "customer_id": transaction.customer_id,
            "attempt_count": transaction.attempt_count,
            "max_attempts_allowed": transaction.max_attempts_allowed
        }
    )


def detect_batch(transactions: List[Transaction]) -> List[DetectionResult]:
    """Applies recoverability detection across a list of transactions."""
    return [detect_recoverability(tx) for tx in transactions]
