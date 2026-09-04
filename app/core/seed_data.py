import random
import json
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from decimal import Decimal
from app.config import DATABASE_PATH
from app.core.models import (
    Merchant, Customer, Transaction, BusinessRule, AuditLog,
    TransactionStatus, FailureReason, DeclineCategory
)
from app.core.database import (
    reset_db, insert_merchants, insert_customers, insert_transactions,
    insert_business_rules, insert_audit_logs, get_database_counts
)


MERCHANT_PROFILES = [
    ("mch_001", "CloudFlow SaaS", "billing@cloudflow.io", "USD"),
    ("mch_002", "FitPulse Gym Subscription", "support@fitpulse.com", "USD"),
    ("mch_003", "StreamVerse Media", "finance@streamverse.tv", "USD"),
    ("mch_004", "EduCraft Online Learning", "pay@educraft.edu", "USD"),
    ("mch_005", "FreshBites Meal Kits", "accounts@freshbites.co", "USD"),
    ("mch_006", "CodeMetrics DevTools", "sales@codemetrics.dev", "USD"),
    ("mch_007", "GlamourBox Beauty", "billing@glamourbox.com", "USD"),
    ("mch_008", "SecureNet VPN", "finance@securenet.io", "USD"),
    ("mch_009", "PetCare Monthly", "orders@petcaremonthly.com", "USD"),
    ("mch_010", "ZenSpace Yoga App", "billing@zenspace.app", "USD"),
]

FIRST_NAMES = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Dakota", "Quinn", "Avery",
               "Priya", "Rahul", "Ananya", "Vikram", "Neha", "Arjun", "Kavya", "Siddharth", "Rohan", "Meera",
               "Emma", "Liam", "Sophia", "Noah", "Olivia", "James", "Isabella", "Benjamin", "Mia", "Ethan"]

LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
              "Sharma", "Verma", "Patel", "Mehta", "Gupta", "Rao", "Nair", "Singh", "Joshi", "Kumar",
              "Chen", "Wong", "Kim", "Park", "Takahashi", "Nakamura", "Lee", "Mueller", "Dubois", "Silva"]

SUBSCRIPTION_TIERS = ["Basic", "Pro", "Enterprise"]
CARD_BRANDS = ["Visa", "Mastercard", "Amex", "Discover"]
PAYMENT_METHODS = ["credit_card", "debit_card", "upi", "net_banking"]

FAILURE_DISTRIBUTION: List[Tuple[FailureReason, DeclineCategory, float]] = [
    (FailureReason.INSUFFICIENT_FUNDS, DeclineCategory.SOFT_DECLINE, 0.40),
    (FailureReason.TEMPORARY_BANK_FAILURE, DeclineCategory.SOFT_DECLINE, 0.20),
    (FailureReason.EXPIRED_CARD, DeclineCategory.DATA_MISMATCH, 0.15),
    (FailureReason.DO_NOT_HONOR, DeclineCategory.SOFT_DECLINE, 0.10),
    (FailureReason.AUTHENTICATION_FAILURE, DeclineCategory.SOFT_DECLINE, 0.08),
    (FailureReason.FRAUD_STOLEN_CARD, DeclineCategory.HARD_DECLINE, 0.04),
    (FailureReason.ACCOUNT_CLOSED, DeclineCategory.HARD_DECLINE, 0.03),
]


def seed_database(db_path: str = DATABASE_PATH, seed_val: int = 42) -> dict:
    """Generates deterministic synthetic data and seeds the SQLite database."""
    random.seed(seed_val)
    reset_db(db_path)

    base_time = datetime.now(timezone.utc) - timedelta(days=90)

    # 1. Create Merchants
    merchants: List[Merchant] = []
    for mch_id, name, email, curr in MERCHANT_PROFILES:
        merchants.append(
            Merchant(
                merchant_id=mch_id,
                name=name,
                email=email,
                currency=curr,
                created_at=(base_time - timedelta(days=180)).isoformat(),
                is_active=True
            )
        )
    insert_merchants(merchants, db_path)

    # 2. Create Customers (250 customers, ~25 per merchant)
    customers: List[Customer] = []
    cust_counter = 1
    for mch in merchants:
        num_custs = random.randint(22, 28)
        for _ in range(num_custs):
            cust_id = f"cust_{cust_counter:04d}"
            fn = random.choice(FIRST_NAMES)
            ln = random.choice(LAST_NAMES)
            cust_name = f"{fn} {ln}"
            email = f"{fn.lower()}.{ln.lower()}{random.randint(10,999)}@example.com"
            phone = f"+1-555-{random.randint(100,999):03d}-{random.randint(1000,9999):04d}"
            tier = random.choice(SUBSCRIPTION_TIERS)
            ltv = Decimal(str(round(random.uniform(49.0, 2490.0), 2)))
            risk_score = round(random.uniform(0.02, 0.45), 2)
            cust_created = base_time + timedelta(days=random.randint(0, 30))

            customers.append(
                Customer(
                    customer_id=cust_id,
                    merchant_id=mch.merchant_id,
                    name=cust_name,
                    email=email,
                    phone=phone,
                    subscription_tier=tier,
                    lifetime_value=ltv,
                    risk_score=risk_score,
                    created_at=cust_created.isoformat()
                )
            )
            cust_counter += 1
    insert_customers(customers, db_path)

    # 3. Create Transactions (1,200 transactions)
    transactions: List[Transaction] = []
    audit_logs: List[AuditLog] = []
    tx_counter = 1001
    audit_counter = 5001

    # Map customers by merchant
    mch_cust_map = {}
    for c in customers:
        mch_cust_map.setdefault(c.merchant_id, []).append(c)

    for mch in merchants:
        mch_customers = mch_cust_map[mch.merchant_id]
        for _ in range(120):
            cust = random.choice(mch_customers)
            tx_id = f"tx_{tx_counter}"
            tx_time = base_time + timedelta(days=random.randint(31, 89), hours=random.randint(0, 23))

            if cust.subscription_tier == "Enterprise":
                amount = Decimal(str(round(random.uniform(299.0, 999.0), 2)))
            elif cust.subscription_tier == "Pro":
                amount = Decimal(str(round(random.uniform(49.0, 199.0), 2)))
            else:
                amount = Decimal(str(round(random.uniform(9.99, 39.99), 2)))

            is_success = random.random() < 0.70

            if is_success:
                status = TransactionStatus.SUCCESS
                reason = FailureReason.NONE
                category = DeclineCategory.NONE
                attempts = 1
            else:
                status = TransactionStatus.FAILED
                r = random.random()
                cumulative = 0.0
                reason = FailureReason.INSUFFICIENT_FUNDS
                category = DeclineCategory.SOFT_DECLINE
                for fail_r, fail_c, prob in FAILURE_DISTRIBUTION:
                    cumulative += prob
                    if r <= cumulative:
                        reason = fail_r
                        category = fail_c
                        break

                if category == DeclineCategory.HARD_DECLINE:
                    attempts = 1
                else:
                    attempts = random.choice([1, 1, 2, 2, 3])

            card_brand = random.choice(CARD_BRANDS)
            pay_method = random.choice(PAYMENT_METHODS)

            tx = Transaction(
                transaction_id=tx_id,
                merchant_id=mch.merchant_id,
                customer_id=cust.customer_id,
                amount=amount,
                currency=mch.currency,
                status=status,
                failure_reason=reason,
                decline_category=category,
                attempt_count=attempts,
                max_attempts_allowed=3,
                payment_method_type=pay_method,
                card_brand=card_brand,
                created_at=tx_time.isoformat(),
                updated_at=tx_time.isoformat()
            )
            transactions.append(tx)

            if status == TransactionStatus.FAILED:
                audit_logs.append(
                    AuditLog(
                        log_id=f"audit_{audit_counter}",
                        transaction_id=tx_id,
                        actor="SYSTEM",
                        action_taken="PAYMENT_FAILED_DETECTED",
                        previous_status=None,
                        new_status=str(TransactionStatus.FAILED),
                        details_json=json.dumps({
                            "decline_category": str(category),
                            "failure_reason": str(reason),
                            "attempt_count": attempts,
                            "amount": str(amount)
                        }),
                        timestamp=tx_time.isoformat()
                    )
                )
                audit_counter += 1

            tx_counter += 1

    insert_transactions(transactions, db_path)

    # 4. Create Business Rules for each merchant
    business_rules: List[BusinessRule] = []
    rule_counter = 1
    for mch in merchants:
        business_rules.extend([
            BusinessRule(
                rule_id=f"rule_{rule_counter:03d}",
                merchant_id=mch.merchant_id,
                rule_name="Max Retry Limit Guardrail",
                rule_type="MAX_RETRIES",
                parameters_json=json.dumps({"max_retries": 3, "retry_window_days": 7}),
                is_enabled=True,
                created_at=base_time.isoformat()
            ),
            BusinessRule(
                rule_id=f"rule_{rule_counter+1:03d}",
                merchant_id=mch.merchant_id,
                rule_name="Block Hard Declines",
                rule_type="HARD_DECLINE_BLOCK",
                parameters_json=json.dumps({"allow_stolen_card_retry": False, "allow_closed_account_retry": False}),
                is_enabled=True,
                created_at=base_time.isoformat()
            ),
            BusinessRule(
                rule_id=f"rule_{rule_counter+2:03d}",
                merchant_id=mch.merchant_id,
                rule_name="Minimum Recovery Probability Threshold",
                rule_type="MIN_PROBABILITY",
                parameters_json=json.dumps({"min_probability": 0.15}),
                is_enabled=True,
                created_at=base_time.isoformat()
            ),
            BusinessRule(
                rule_id=f"rule_{rule_counter+3:03d}",
                merchant_id=mch.merchant_id,
                rule_name="Incentive Discount Cap",
                rule_type="MAX_DISCOUNT_PCT",
                parameters_json=json.dumps({"max_discount_pct": 20.0}),
                is_enabled=True,
                created_at=base_time.isoformat()
            )
        ])
        rule_counter += 4

    insert_business_rules(business_rules, db_path)
    insert_audit_logs(audit_logs, db_path)

    counts = get_database_counts(db_path)
    return counts


if __name__ == "__main__":
    print("Seeding database with synthetic dataset...")
    result_counts = seed_database()
    print("Database seeding completed successfully!")
    print("Table Row Counts:")
    for tbl, count in result_counts.items():
        print(f"  - {tbl}: {count}")
