import json
from typing import Optional, Dict, Any
from app.core.models import Transaction, Customer


SYSTEM_INSTRUCTION = """You are an expert payment revenue recovery analyst for Recovera AI.

Your job is to:
1. Diagnose the root cause of payment failure based on transaction metadata and customer context.
2. Determine whether the payment appears recoverable.
3. Estimate the recovery probability (as a float between 0.0 and 1.0).
4. Recommend the safest, most effective recovery action from the allowed action list.
5. Recommend an appropriate retry delay in hours (integer >= 0).
6. Draft an empathetic, clear customer outreach message if customer communication is recommended.

IMPORTANT SAFETY & COMPLIANCE RULES:
- You are providing a RECOMMENDATION ONLY. You do NOT execute any action.
- Never claim an action has already been executed.
- Never override merchant business rules.
- Never recommend retrying a hard decline (such as fraud, stolen card, or closed account).
- Never exceed the maximum retry attempt limit.
- If uncertain or risk score is high, recommend MANUAL_REVIEW rather than inventing facts.
- The recommended_action field MUST be exactly one of the following string enum values:
  * "SMART_RETRY"
  * "DUNNING_EMAIL"
  * "PAYMENT_LINK_SMS"
  * "INCENTIVIZED_RETRY"
  * "MANUAL_REVIEW"
  * "NO_ACTION_BLOCK"

You MUST return ONLY a valid JSON object matching the requested schema. Do not include markdown code fences or conversational text outside the JSON object."""


JSON_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "transaction_id": {"type": "string"},
        "failure_diagnosis": {"type": "string"},
        "failure_category": {"type": "string", "enum": ["SOFT_DECLINE", "HARD_DECLINE", "DATA_MISMATCH", "NONE"]},
        "recovery_probability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "recommended_action": {
            "type": "string",
            "enum": [
                "SMART_RETRY",
                "DUNNING_EMAIL",
                "PAYMENT_LINK_SMS",
                "INCENTIVIZED_RETRY",
                "MANUAL_REVIEW",
                "NO_ACTION_BLOCK"
            ]
        },
        "retry_delay_hours": {"type": "integer", "minimum": 0},
        "customer_message_draft": {"type": "string"},
        "confidence_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reasoning": {"type": "string"}
    },
    "required": [
        "transaction_id",
        "failure_diagnosis",
        "failure_category",
        "recovery_probability",
        "recommended_action",
        "retry_delay_hours",
        "confidence_score",
        "reasoning"
    ]
}


def build_diagnostic_user_prompt(
    transaction: Transaction,
    customer: Optional[Customer] = None,
    history_summary: Optional[Dict[str, Any]] = None
) -> str:
    """Constructs a structured prompt for Gemini AI diagnostic analysis."""
    context = {
        "transaction": {
            "transaction_id": transaction.transaction_id,
            "amount": float(transaction.amount),
            "currency": transaction.currency,
            "status": str(transaction.status),
            "failure_reason": str(transaction.failure_reason),
            "decline_category": str(transaction.decline_category),
            "attempt_count": transaction.attempt_count,
            "max_attempts_allowed": transaction.max_attempts_allowed,
            "payment_method_type": transaction.payment_method_type,
            "card_brand": transaction.card_brand,
            "created_at": transaction.created_at
        },
        "customer": {
            "customer_id": customer.customer_id if customer else transaction.customer_id,
            "name": customer.name if customer else "Unknown",
            "subscription_tier": customer.subscription_tier if customer else "Pro",
            "lifetime_value": float(customer.lifetime_value) if customer else 0.0,
            "risk_score": customer.risk_score if customer else 0.1
        } if customer else None,
        "historical_patterns": history_summary or {
            "previous_successful_payments": 5,
            "previous_failed_payments": transaction.attempt_count - 1,
            "recent_card_updates": False
        }
    }

    return f"""Please analyze the following payment failure context and generate a structured recovery diagnosis:

CONTEXT DATA:
{json.dumps(context, indent=2)}

Provide your response strictly in valid JSON format matching this schema:
{json.dumps(JSON_RESPONSE_SCHEMA, indent=2)}
"""
