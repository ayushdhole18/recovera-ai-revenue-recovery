import sqlite3
from typing import List, Optional, Dict, Any
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
from app.config import DATABASE_PATH
from app.core.models import Merchant, Customer, Transaction, Diagnostic, BusinessRule, AuditLog


def get_connection(db_path: str = DATABASE_PATH) -> sqlite3.Connection:
    """Creates and returns a SQLite database connection with row factory and foreign keys configured."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DATABASE_PATH) -> None:
    """Initializes SQLite database tables and append-only triggers if they do not exist."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Create tables
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS merchants (
            merchant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            created_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            subscription_tier TEXT NOT NULL DEFAULT 'Pro',
            lifetime_value REAL NOT NULL DEFAULT 0.0,
            risk_score REAL NOT NULL DEFAULT 0.1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (merchant_id) REFERENCES merchants (merchant_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            status TEXT NOT NULL,
            failure_reason TEXT NOT NULL,
            decline_category TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            max_attempts_allowed INTEGER NOT NULL DEFAULT 3,
            payment_method_type TEXT NOT NULL,
            card_brand TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (merchant_id) REFERENCES merchants (merchant_id) ON DELETE CASCADE,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS diagnostics (
            diagnostic_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            detected_root_cause TEXT NOT NULL,
            is_recoverable INTEGER NOT NULL DEFAULT 1,
            confidence_score REAL NOT NULL,
            estimated_recovery_probability REAL NOT NULL,
            recommended_action TEXT NOT NULL,
            recommended_delay_hours INTEGER NOT NULL,
            raw_ai_reasoning TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS business_rules (
            rule_id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            rule_name TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (merchant_id) REFERENCES merchants (merchant_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS audit_trail (
            log_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            previous_status TEXT,
            new_status TEXT,
            details_json TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id) ON DELETE CASCADE
        );

        -- AUDIT TRAIL IMMUTABILITY & APPEND-ONLY TRIGGERS
        -- Prevents accidental or malicious modification/deletion of audit trail records.
        CREATE TRIGGER IF NOT EXISTS prevent_audit_update
        BEFORE UPDATE ON audit_trail
        BEGIN
            SELECT RAISE(FAIL, 'Audit trail records are immutable and append-only. UPDATE operations are prohibited.');
        END;

        CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
        BEFORE DELETE ON audit_trail
        BEGIN
            SELECT RAISE(FAIL, 'Audit trail records are immutable and append-only. DELETE operations are prohibited.');
        END;
    """)

    conn.commit()
    conn.close()


def reset_db(db_path: str = DATABASE_PATH) -> None:
    """Drops all tables and re-creates schema (including append-only triggers)."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.executescript("""
        PRAGMA foreign_keys = OFF;
        DROP TRIGGER IF EXISTS prevent_audit_update;
        DROP TRIGGER IF EXISTS prevent_audit_delete;
        DROP TABLE IF EXISTS audit_trail;
        DROP TABLE IF EXISTS business_rules;
        DROP TABLE IF EXISTS diagnostics;
        DROP TABLE IF EXISTS transactions;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS merchants;
        PRAGMA foreign_keys = ON;
    """)

    conn.commit()
    conn.close()
    init_db(db_path)


# Insertion & Update helper functions using Pydantic models

def insert_merchants(merchants: List[Merchant], db_path: str = DATABASE_PATH) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO merchants (merchant_id, name, email, currency, created_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(m.merchant_id, m.name, m.email, m.currency, m.created_at, 1 if m.is_active else 0) for m in merchants]
    )
    conn.commit()
    conn.close()


def insert_customers(customers: List[Customer], db_path: str = DATABASE_PATH) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO customers (customer_id, merchant_id, name, email, phone, subscription_tier, lifetime_value, risk_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(c.customer_id, c.merchant_id, c.name, c.email, c.phone, c.subscription_tier, float(c.lifetime_value), c.risk_score, c.created_at) for c in customers]
    )
    conn.commit()
    conn.close()


def insert_transactions(transactions: List[Transaction], db_path: str = DATABASE_PATH) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO transactions (
            transaction_id, merchant_id, customer_id, amount, currency, status,
            failure_reason, decline_category, attempt_count, max_attempts_allowed,
            payment_method_type, card_brand, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                t.transaction_id, t.merchant_id, t.customer_id, float(t.amount), t.currency,
                t.status.value if hasattr(t.status, "value") else str(t.status),
                t.failure_reason.value if hasattr(t.failure_reason, "value") else str(t.failure_reason),
                t.decline_category.value if hasattr(t.decline_category, "value") else str(t.decline_category),
                t.attempt_count, t.max_attempts_allowed, t.payment_method_type,
                t.card_brand, t.created_at, t.updated_at
            )
            for t in transactions
        ]
    )
    conn.commit()
    conn.close()


def update_transaction_status(
    transaction_id: str,
    new_status: Any,
    new_attempt_count: int,
    db_path: str = DATABASE_PATH
) -> None:
    """Updates status, attempt_count, and updated_at for a given transaction."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    status_str = new_status.value if hasattr(new_status, "value") else str(new_status)

    cursor.execute(
        """
        UPDATE transactions
        SET status = ?, attempt_count = ?, updated_at = ?
        WHERE transaction_id = ?
        """,
        (status_str, new_attempt_count, now_iso, transaction_id)
    )
    conn.commit()
    conn.close()


def insert_diagnostics(diagnostics: List[Diagnostic], db_path: str = DATABASE_PATH) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO diagnostics (
            diagnostic_id, transaction_id, detected_root_cause, is_recoverable,
            confidence_score, estimated_recovery_probability, recommended_action,
            recommended_delay_hours, raw_ai_reasoning, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                d.diagnostic_id, d.transaction_id, d.detected_root_cause, 1 if d.is_recoverable else 0,
                d.confidence_score, d.estimated_recovery_probability,
                d.recommended_action.value if hasattr(d.recommended_action, "value") else str(d.recommended_action),
                d.recommended_delay_hours, d.raw_ai_reasoning, d.created_at
            )
            for d in diagnostics
        ]
    )
    conn.commit()
    conn.close()


def insert_business_rules(rules: List[BusinessRule], db_path: str = DATABASE_PATH) -> None:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO business_rules (
            rule_id, merchant_id, rule_name, rule_type, parameters_json, is_enabled, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [(r.rule_id, r.merchant_id, r.rule_name, r.rule_type, r.parameters_json, 1 if r.is_enabled else 0, r.created_at) for r in rules]
    )
    conn.commit()
    conn.close()


# AUDIT TRAIL API - APPEND ONLY CONTRACT
# Note: Audit trail records are strictly append-only. Only INSERT operations are supported.
# UPDATE and DELETE queries are blocked at both database trigger and API layers.

def insert_audit_logs(audit_logs: List[AuditLog], db_path: str = DATABASE_PATH) -> None:
    """Appends new audit trail log entries. Does not support modifying or deleting existing logs."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO audit_trail (
            log_id, transaction_id, actor, action_taken, previous_status, new_status, details_json, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                a.log_id, a.transaction_id, a.actor, a.action_taken,
                a.previous_status.value if hasattr(a.previous_status, "value") else (str(a.previous_status) if a.previous_status is not None else None),
                a.new_status.value if hasattr(a.new_status, "value") else (str(a.new_status) if a.new_status is not None else None),
                a.details_json, a.timestamp
            )
            for a in audit_logs
        ]
    )
    conn.commit()
    conn.close()


def get_database_counts(db_path: str = DATABASE_PATH) -> Dict[str, int]:
    """Returns row counts for all 6 core tables."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    counts = {}
    for table in ["merchants", "customers", "transactions", "diagnostics", "business_rules", "audit_trail"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cursor.fetchone()[0]

    conn.close()
    return counts
