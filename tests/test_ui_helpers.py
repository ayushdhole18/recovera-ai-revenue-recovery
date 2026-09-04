import os
import shutil
import tempfile
import pytest
from decimal import Decimal
import pandas as pd
from app.config import DATABASE_PATH
from app.core.models import TransactionStatus
from app.services.ui_helpers import (
    get_merchant_dropdown_options, load_transaction_grid_dataframe,
    get_dashboard_analytics_summary, preview_single_transaction_pipeline,
    execute_single_transaction_recovery
)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name
    shutil.copy(DATABASE_PATH, temp_db_path)
    yield temp_db_path
    if os.path.exists(temp_db_path):
        try:
            os.remove(temp_db_path)
        except OSError:
            pass


def test_get_merchant_dropdown_options(temp_db):
    options = get_merchant_dropdown_options(temp_db)
    assert len(options) >= 1
    assert options[0]["id"] == "ALL"
    assert "All Merchants" in options[0]["label"]


def test_load_transaction_grid_dataframe(temp_db):
    df = load_transaction_grid_dataframe(temp_db)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "transaction_id" in df.columns
    assert "amount" in df.columns
    assert "amount_formatted" in df.columns

    # Test filtering by merchant
    mch_id = df.iloc[0]["merchant_id"]
    df_mch = load_transaction_grid_dataframe(temp_db, merchant_id=mch_id)
    assert not df_mch.empty
    assert (df_mch["merchant_id"] == mch_id).all()


def test_get_dashboard_analytics_summary(temp_db):
    summary = get_dashboard_analytics_summary(temp_db)
    assert "hero_metrics" in summary
    assert "secondary_metrics" in summary
    assert "funnel" in summary
    assert "leakage_breakdown" in summary
    assert "action_performance" in summary
    assert summary["hero_metrics"]["total_failed_revenue"] > Decimal("0.00")
    assert summary["hero_metrics"]["revenue_recovery_rate_pct"] >= 0.0


def test_preview_does_not_execute_recovery(temp_db):
    df = load_transaction_grid_dataframe(temp_db)
    first_tx_id = df.iloc[0]["transaction_id"]

    # Preview pipeline (Read Only)
    preview = preview_single_transaction_pipeline(first_tx_id, db_path=temp_db)
    assert preview["step_1_failed_payment"].transaction_id == first_tx_id
    assert preview["step_7_execution_result"] is None  # Zero execution side-effect!
    assert preview["step_8_revenue_recovered"] is None


def test_explicit_execution_trigger(temp_db):
    df = load_transaction_grid_dataframe(temp_db)
    failed_txs = df[df["status"] == "FAILED"]
    if failed_txs.empty:
        pytest.skip("No failed transaction available to test execution.")

    tx_id = failed_txs.iloc[0]["transaction_id"]

    preview = preview_single_transaction_pipeline(tx_id, db_path=temp_db)
    ai_diag = preview["step_3_ai_diagnosis"]
    rule_val = preview["step_6_safety_check"]

    if not rule_val.is_allowed:
        pytest.skip("Transaction blocked by safety rule engine; execution skipped.")

    exec_output = execute_single_transaction_recovery(tx_id, ai_diag, rule_val, db_path=temp_db)
    assert exec_output["execution_result"] is not None
    assert exec_output["execution_result"].transaction_id == tx_id
    assert exec_output["step_8_revenue_recovered"]["status"] in ["RECOVERED", "SOFT_FAILED", "HARD_FAILED", "MANUAL_REVIEW"]
