import os
import sys
import json
from pathlib import Path
from decimal import Decimal
import streamlit as st
import pandas as pd

# Add project root directory to sys.path for clean imports
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from app.config import DATABASE_PATH
from app.core.database import ensure_database_initialized
from app.core.models import TransactionStatus, CalibrationBucket

from app.utils.currency import format_inr, convert_usd_to_inr
from app.services.ui_helpers import (
    get_merchant_dropdown_options, load_transaction_grid_dataframe,
    get_dashboard_analytics_summary, preview_single_transaction_pipeline,
    execute_single_transaction_recovery, get_merchant_rules_overview,
    get_evaluation_metrics_summary
)
from app.services.analytics import get_all_audit_logs

from app.components.metric_card import render_metric_card
from app.components.status_badge import render_status_badge
from app.components.safety_banner import render_safety_banner
from app.components.workflow_stepper import render_workflow_stepper
from app.components.charts import (
    build_recovery_funnel_chart, build_revenue_leakage_chart,
    build_action_performance_chart, build_calibration_chart
)

# Page Configuration
st.set_page_config(
    page_title="Recovera AI - Revenue Recovery Platform",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load CSS Styling System
css_path = root_path / "assets" / "style.css"
if css_path.exists():
    with open(css_path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


def render_header():
    """Renders global header telemetry bar and returns selected merchant ID."""
    merchants = get_merchant_dropdown_options(DATABASE_PATH)
    merchant_labels = [m["label"] for m in merchants]
    merchant_map = {m["label"]: m["id"] for m in merchants}

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        ai_engine_badge = render_status_badge("GEMINI 2.5 FLASH")
    else:
        ai_engine_badge = render_status_badge("DETERMINISTIC FALLBACK")

    sys_status_badge = render_status_badge("ALLOWED")  # System Online

    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        st.markdown('<div class="brand-title">⚡ Recovera AI</div>', unsafe_allow_html=True)
    with col2:
        selected_mch_label = st.selectbox("Merchant Filter", merchant_labels, index=0, label_visibility="collapsed")
        selected_mch_id = merchant_map[selected_mch_label]
    with col3:
        st.markdown(
            f'<div style="text-align: right;">Engine: {ai_engine_badge} System: {sys_status_badge}</div>',
            unsafe_allow_html=True
        )

    st.markdown("---")
    return selected_mch_id


def render_executive_dashboard(merchant_id: str):
    """Renders Page 1: Executive Dashboard."""
    st.markdown("## 📊 Executive Revenue Operations Dashboard")
    st.caption("Real-time revenue risk telemetry, recovery rate metrics, and funnel analysis.")

    summary = get_dashboard_analytics_summary(DATABASE_PATH, merchant_id=merchant_id)
    hero = summary["hero_metrics"]
    sec = summary["secondary_metrics"]

    # 1. Hero Financial Metric Cards (in INR)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_card("Revenue at Risk", hero["total_failed_revenue"], "Total value of all failed payments")
    with c2:
        render_metric_card("Potentially Recoverable", hero["potentially_recoverable_revenue"], "Soft declines & recoverable errors")
    with c3:
        render_metric_card("Revenue Recovered", hero["recovered_revenue"], "Recovered via automated strategies")
    with c4:
        render_metric_card("Revenue Recovery Rate", hero["revenue_recovery_rate_pct"], "Recovered / Potentially Recoverable")

    st.markdown("<br/>", unsafe_allow_html=True)

    # Secondary Metrics Row
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        render_metric_card("Failed Transactions", sec["total_failed_transactions"], "Total failed payments count")
    with sc2:
        render_metric_card("Recoverable Count", sec["recoverable_transactions"], "Target recoverable transactions")
    with sc3:
        render_metric_card("Successful Recoveries", sec["successful_recoveries"], "Transactions successfully recovered")
    with sc4:
        render_metric_card("Blocked Actions", sec["blocked_actions"], "Blocked by Merchant Safety Rules")

    st.markdown("<br/>", unsafe_allow_html=True)

    # 2. Recovery Funnel & Revenue Leakage
    col_f, col_l = st.columns([1, 1])
    with col_f:
        funnel_fig = build_recovery_funnel_chart(summary["funnel"])
        st.plotly_chart(funnel_fig, use_container_width=True)

    with col_l:
        leakage_fig = build_revenue_leakage_chart(summary["leakage_breakdown"])
        st.plotly_chart(leakage_fig, use_container_width=True)

    st.markdown("<br/>", unsafe_allow_html=True)

    # 3. Action Performance Breakdown
    st.markdown("### ⚡ Recovery Action Performance")
    action_fig = build_action_performance_chart(summary["action_performance"])
    st.plotly_chart(action_fig, use_container_width=True)


def render_at_risk_transactions(merchant_id: str):
    """Renders Page 2: At-Risk Transactions Grid (Screen 1)."""
    st.markdown("## ⚠️ At-Risk Transactions Workspace")
    st.caption("Search, filter, and inspect failed payments requiring recovery intervention.")

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        search_query = st.text_input("🔍 Search Transaction, Customer, Merchant", "")
    with c2:
        status_filter = st.selectbox("Status Filter", ["ALL", "FAILED", "RECOVERED", "UNRECOVERABLE"], index=0)
    with c3:
        category_filter = st.selectbox("Decline Category", ["ALL", "SOFT_DECLINE", "HARD_DECLINE"], index=0)
    with c4:
        rec_filter = st.selectbox("Recoverability", ["ALL", "RECOVERABLE", "UNRECOVERABLE"], index=0)

    df = load_transaction_grid_dataframe(
        DATABASE_PATH,
        merchant_id=merchant_id,
        status_filter=status_filter,
        category_filter=category_filter,
        recoverable_filter=rec_filter
    )

    if search_query:
        mask = (
            df["transaction_id"].str.contains(search_query, case=False, na=False) |
            df["customer_name"].str.contains(search_query, case=False, na=False) |
            df["merchant_name"].str.contains(search_query, case=False, na=False)
        )
        df = df[mask]

    st.markdown(f"**Showing {len(df)} transactions**")

    # Display grid with action buttons
    for idx, row in df.iterrows():
        tx_id = row["transaction_id"]
        amt_str = row["amount_formatted"]
        reason = row["failure_reason"]
        category = row["decline_category"]
        status = row["status"]
        is_rec = row["is_recoverable"]

        with st.container():
            col1, col2, col3, col4, col5 = st.columns([2.2, 2, 2, 1.8, 2])
            with col1:
                st.markdown(f"**`{tx_id}`**")
                st.caption(f"{row['customer_name']} ({row['subscription_tier']})")
            with col2:
                st.markdown(f"**{amt_str}**")
                st.caption(f"{row['payment_method_type']} - {row['card_brand']}")
            with col3:
                st.markdown(f"<code>{reason}</code>", unsafe_allow_html=True)
                st.caption(f"Attempts: {row['attempt_count']}/{row['max_attempts_allowed']}")
            with col4:
                rec_badge = render_status_badge("RECOVERABLE" if is_rec else "UNRECOVERABLE")
                st.markdown(f"{render_status_badge(status)} {rec_badge}", unsafe_allow_html=True)
            with col5:
                if st.button("🔍 Inspect Stepper", key=f"btn_inspect_{tx_id}"):
                    st.session_state["selected_tx_id"] = tx_id
                    st.session_state["nav_selection"] = "3. Transaction Detail & Stepper"
                    st.rerun()
            st.markdown("<hr style='margin: 4px 0; border-color: #26354D;'/>", unsafe_allow_html=True)


def render_transaction_detail():
    """Renders Page 3: Transaction Detail & 8-Step Stepper Workflow."""
    st.markdown("## 🔍 Transaction Detail & 8-Step Recovery Stepper")
    st.caption("Interactive hackathon demonstration: Step-by-step telemetry from failure detection to execution.")

    df_tx = load_transaction_grid_dataframe(DATABASE_PATH)
    all_tx_ids = df_tx["transaction_id"].tolist()

    default_tx = st.session_state.get("selected_tx_id", all_tx_ids[0] if all_tx_ids else "")
    selected_tx_id = st.selectbox("Select Transaction to Inspect", all_tx_ids, index=all_tx_ids.index(default_tx) if default_tx in all_tx_ids else 0)

    if not selected_tx_id:
        st.warning("No transactions available to display.")
        return

    # READ ONLY PIPELINE PREVIEW (Zero execution on load!)
    preview_data = preview_single_transaction_pipeline(selected_tx_id, db_path=DATABASE_PATH)

    tx = preview_data["step_1_failed_payment"]
    cust = preview_data["customer_info"]
    det = preview_data["step_2_recovery_detector"]
    ai = preview_data["step_3_ai_diagnosis"]
    prob_info = preview_data["step_4_recovery_probability"]
    rec_info = preview_data["step_5_recommended_action"]
    safety = preview_data["step_6_safety_check"]

    # Metadata Summary Header Card
    with st.container():
        st.markdown(
            f"""
            <div class="fintech-card" style="margin-bottom: 20px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <div style="font-size: 1.2rem; font-weight: 700; color: #F8FAFC;">Transaction {tx.transaction_id}</div>
                        <div style="font-size: 0.85rem; color: #94A3B8;">Customer: <strong>{cust['name']}</strong> ({cust['email']}) | Risk Score: <code>{cust['risk_score']}</code></div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-size: 1.4rem; font-weight: 700; color: #10B981;">{format_inr(tx.amount)}</div>
                        <div>{render_status_badge(tx.status)}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # 8-Step Interactive Stepper Display
    st.markdown("### 8-Step Recovery Pipeline Stepper")

    # Steps 1 to 6
    st.markdown('<div class="stepper-container">', unsafe_allow_html=True)

    # Step 1
    st.markdown(f"""
    <div class="stepper-item">
        <div class="stepper-number">1</div>
        <div class="stepper-content">
            <div class="stepper-title">STEP 1 — PAYMENT FAILED</div>
            <div class="stepper-body">
                Amount: <strong>{format_inr(tx.amount)}</strong> | Failure Reason: <code>{tx.failure_reason}</code><br/>
                Payment Method: {tx.payment_method_type} ({tx.card_brand}) | Attempt Count: {tx.attempt_count}/{tx.max_attempts_allowed}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Step 2
    det_badge = render_status_badge("RECOVERABLE" if det.is_recoverable else "UNRECOVERABLE")
    st.markdown(f"""
    <div class="stepper-item">
        <div class="stepper-number">2</div>
        <div class="stepper-content">
            <div class="stepper-title">STEP 2 — RECOVERY DETECTION {det_badge}</div>
            <div class="stepper-body">
                Decline Category: <code>{det.decline_category}</code> | Recoverable: <strong>{'YES' if det.is_recoverable else 'NO'}</strong><br/>
                Detector Next Step: {det.recommended_next_step}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Step 3
    engine_label = "GEMINI 2.5 FLASH" if not ai.is_fallback else "DETERMINISTIC FALLBACK"
    fb_badge = render_status_badge("FALLBACK" if ai.is_fallback else "GEMINI LIVE")
    st.markdown(f"""
    <div class="stepper-item">
        <div class="stepper-number">3</div>
        <div class="stepper-content">
            <div class="stepper-title">STEP 3 — AI DIAGNOSIS AGENT ({engine_label}) {fb_badge}</div>
            <div class="stepper-body">
                <strong>Diagnosis:</strong> {ai.failure_diagnosis}<br/>
                <strong>AI Reasoning:</strong> {ai.reasoning}<br/>
                <strong>Outreach Message Draft:</strong> <em>"{ai.customer_message_draft or 'N/A'}"</em>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Step 4
    st.markdown(f"""
    <div class="stepper-item">
        <div class="stepper-number">4</div>
        <div class="stepper-content">
            <div class="stepper-title">STEP 4 — RECOVERY PROBABILITY ESTIMATE</div>
            <div class="stepper-body">
                Estimated Probability Score: <strong>{prob_info['probability']:.2f}</strong> (Calibration Bucket: <code>{prob_info['bucket']}</code>)<br/>
                AI Confidence Score: {prob_info['confidence']:.2f}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Step 5
    st.markdown(f"""
    <div class="stepper-item">
        <div class="stepper-number">5</div>
        <div class="stepper-content">
            <div class="stepper-title">STEP 5 — RECOMMENDED ACTION PROPOSAL</div>
            <div class="stepper-body">
                Proposed Action: <code>{rec_info['proposed_action']}</code> | Recommended Delay: {rec_info['retry_delay_hours']} hours
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Step 6: Safety Check
    st.markdown('<div class="stepper-item"><div class="stepper-number">6</div><div class="stepper-content"><div class="stepper-title">STEP 6 — SAFETY CHECK & RULE VALIDATION</div>', unsafe_allow_html=True)
    orig_act_str = safety.original_action.value if hasattr(safety.original_action, "value") else str(safety.original_action)
    fin_act_str = safety.final_action.value if hasattr(safety.final_action, "value") else str(safety.final_action)
    render_safety_banner(
        original_action=orig_act_str,
        is_allowed=safety.is_allowed,
        final_action=fin_act_str,
        violated_rules=safety.violated_rules,
        explanation=safety.explanation
    )
    st.markdown('</div></div>', unsafe_allow_html=True)

    # Step 7: Interactive Execution Trigger (CRITICAL SAFETY FEATURE)
    st.markdown('<div class="stepper-item"><div class="stepper-number">7</div><div class="stepper-content"><div class="stepper-title">STEP 7 — RECOVERY EXECUTION ENGINE</div>', unsafe_allow_html=True)

    # Check session state for prior execution in this session
    exec_state_key = f"exec_res_{selected_tx_id}"
    exec_data = st.session_state.get(exec_state_key)

    if not safety.is_allowed:
        st.error(f"🚫 EXECUTION BLOCKED: Merchant Safety Policy prevents execution of action `{orig_act_str}`. Safety Outcome: `{fin_act_str}`.")
    else:
        if exec_data is None:
            st.info("⚡ Execution Pending: Recovery strategy is validated and ready for execution.")
            if st.button("⚡ Execute Recovery Strategy", key=f"btn_exec_{selected_tx_id}"):
                with st.spinner("Invoking Payment Recovery Simulator..."):
                    exec_result_dict = execute_single_transaction_recovery(
                        selected_tx_id, ai_diag=ai, rule_val=safety, db_path=DATABASE_PATH
                    )
                    st.session_state[exec_state_key] = exec_result_dict
                    st.rerun()
        else:
            exec_res = exec_data["execution_result"]
            st.success(f"✓ Action Executed: `{exec_res.action}` | Status: `{exec_res.execution_status}` | Latency: {exec_res.execution_time_ms}ms")
            st.caption(f"Gateway Response Code: {exec_res.gateway_response_code} | Message: {exec_res.message}")

    st.markdown('</div></div>', unsafe_allow_html=True)

    # Step 8: Revenue Recovered Impact
    st.markdown('<div class="stepper-item"><div class="stepper-number">8</div><div class="stepper-content"><div class="stepper-title">STEP 8 — REVENUE RECOVERED IMPACT</div>', unsafe_allow_html=True)
    if exec_data and exec_data["step_8_revenue_recovered"]["is_success"]:
        rec_amt = exec_data["step_8_revenue_recovered"]["recovered_amount"]
        st.markdown(f'<div style="font-size: 1.2rem; font-weight: 700; color: #10B981;">🎉 REVENUE RECOVERED: {format_inr(rec_amt, is_converted=True)}</div>', unsafe_allow_html=True)
    elif tx.status == TransactionStatus.RECOVERED:
        st.markdown(f'<div style="font-size: 1.2rem; font-weight: 700; color: #10B981;">🎉 REVENUE RECOVERED: {format_inr(tx.amount)}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div>Status: <strong>NOT RECOVERED / PENDING EXECUTION</strong></div>', unsafe_allow_html=True)
    st.markdown('</div></div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Audit Trail Compact Preview
    st.markdown("---")
    st.markdown("### 📜 Compact Audit Trail Lifecycle Preview")

    active_timeline = exec_data["audit_timeline"] if exec_data else preview_data["audit_timeline"]
    if active_timeline:
        st.markdown("**Detector ──► AI Agent ──► Rule Engine ──► Executor**")
        for log_entry in active_timeline:
            st.markdown(
                f"- `[{log_entry['timestamp']}]` **{log_entry['actor']}** $\\rightarrow$ `{log_entry['action_taken']}` (Status: `{log_entry['new_status']}`)"
            )
    else:
        st.info("No audit entries appended yet for this transaction.")


def render_ai_recovery_agent():
    """Renders Screen 2: AI Recovery Agent Explanation & Inspector."""
    st.markdown("## 🧠 AI Recovery Agent Inspector")
    st.caption("Inspect how Recovera AI diagnoses failure root cause and proposes customized recovery strategies.")

    st.warning("⚠️ **SAFETY POLICY**: AI recommendations are strictly advisory. AI NEVER directly executes financial recovery. All proposed actions must be validated by the Safety Rule Engine first.")

    df_tx = load_transaction_grid_dataframe(DATABASE_PATH)
    all_tx_ids = df_tx["transaction_id"].tolist()

    default_tx = st.session_state.get("selected_tx_id", all_tx_ids[0] if all_tx_ids else "")
    selected_tx_id = st.selectbox("Select Transaction to Inspect AI Diagnosis", all_tx_ids, index=all_tx_ids.index(default_tx) if default_tx in all_tx_ids else 0)

    if not selected_tx_id:
        st.warning("No transactions available.")
        return

    preview_data = preview_single_transaction_pipeline(selected_tx_id, db_path=DATABASE_PATH)
    tx = preview_data["step_1_failed_payment"]
    cust = preview_data["customer_info"]
    ai = preview_data["step_3_ai_diagnosis"]
    prob_info = preview_data["step_4_recovery_probability"]
    rec_info = preview_data["step_5_recommended_action"]
    safety = preview_data["step_6_safety_check"]

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(
            f"""
            <div class="fintech-card">
                <h3>📌 Selected Transaction</h3>
                <p>Transaction ID: <code>{tx.transaction_id}</code></p>
                <p>Merchant: <code>{tx.merchant_id}</code> | Customer: <strong>{cust['name']}</strong></p>
                <p>Amount: <strong>{format_inr(tx.amount)}</strong></p>
                <p>Failure Reason: <code>{tx.failure_reason}</code></p>
                <p>Decline Category: <code>{tx.decline_category}</code></p>
            </div>
            """,
            unsafe_allow_html=True
        )
    with c2:
        engine_label = "GEMINI 2.5 FLASH LIVE" if not ai.is_fallback else "DETERMINISTIC FALLBACK ENGINE"
        badge = render_status_badge("FALLBACK" if ai.is_fallback else "GEMINI LIVE")
        st.markdown(
            f"""
            <div class="fintech-card">
                <h3>⚙️ AI Engine Status {badge}</h3>
                <p>Active Model: <strong>{engine_label}</strong></p>
                <p>Confidence Score: <strong>{ai.confidence_score:.2f}</strong></p>
                <p>Fallback Triggered: <code>{ai.is_fallback}</code></p>
                <p>Latency Guarantee: Sub-500ms deterministic fallback available if API times out.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 🔍 AI Agent Diagnosis & Proposal Breakdown")

    col_diag, col_rec = st.columns([1, 1])
    with col_diag:
        st.markdown(
            f"""
            <div class="fintech-card">
                <h4>Diagnosis & Reasoning</h4>
                <p><strong>Root Cause:</strong> {ai.failure_diagnosis}</p>
                <p><strong>AI Reasoning:</strong> {ai.reasoning}</p>
                <p><strong>Customer Message Draft:</strong></p>
                <blockquote style="background: rgba(11, 15, 23, 0.6); padding: 10px; border-left: 3px solid #6366F1; color: #F8FAFC;">
                    "{ai.customer_message_draft or 'N/A'}"
                </blockquote>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_rec:
        st.markdown(
            f"""
            <div class="fintech-card">
                <h4>Proposal Metrics & Strategy</h4>
                <p><strong>Estimated Recovery Probability:</strong> <span style="font-size: 1.2rem; font-weight: 700; color: #10B981;">{prob_info['probability']:.2f}</span> (Bucket: <code>{prob_info['bucket']}</code>)</p>
                <p><strong>Recommended Strategy:</strong> <code>{rec_info['proposed_action']}</code></p>
                <p><strong>Recommended Retry Delay:</strong> {rec_info['retry_delay_hours']} hours</p>
                <hr style="border-color: #26354D;"/>
                <p><strong>Rule Engine Validation Status:</strong></p>
            </div>
            """,
            unsafe_allow_html=True
        )
        orig_act_str = safety.original_action.value if hasattr(safety.original_action, "value") else str(safety.original_action)
        fin_act_str = safety.final_action.value if hasattr(safety.final_action, "value") else str(safety.final_action)
        render_safety_banner(
            original_action=orig_act_str,
            is_allowed=safety.is_allowed,
            final_action=fin_act_str,
            violated_rules=safety.violated_rules,
            explanation=safety.explanation
        )


def render_safety_rule_engine(merchant_id: str):
    """Renders Screen 3: Safety Rule Engine Configuration & Decision Audit."""
    st.markdown("## 🛡️ Merchant Safety Rule Engine")
    st.caption("The Rule Engine is the FINAL AUTHORITY. AI proposals must comply with merchant policies before execution.")

    st.info("🛡️ **RULE ENGINE MANDATE**: All recovery attempts undergo deterministic validation against active merchant rules. If `is_allowed = False`, execution is completely blocked.")

    overview = get_merchant_rules_overview(merchant_id=merchant_id, db_path=DATABASE_PATH)
    rules = overview["configured_rules"]

    # Rule Summary Metric Cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_card("Evaluated Proposals", overview["total_evaluated"], "Total AI actions checked")
    with c2:
        render_metric_card("Allowed (Approved)", overview["approved_count"], "Approved without changes")
    with c3:
        render_metric_card("Modified Strategy", overview["modified_count"], "Action/discount adjusted")
    with c4:
        render_metric_card("Blocked Actions", overview["blocked_count"], "Prohibited by safety rules")

    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 📋 Active Merchant Business Rules")

    if rules:
        for r in rules:
            r_name = r.get("rule_name", r.get("rule_type", "Rule"))
            r_type = r.get("rule_type", "")
            params_str = r.get("parameters_json", "{}")
            st.markdown(
                f"""
                <div class="fintech-card" style="margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>{r_name}</strong> (Type: <code>{r_type}</code>)<br/>
                            <span style="color: #94A3B8; font-size: 0.85rem;">Config: <code>{params_str}</code></span>
                        </div>
                        <div>
                            {render_status_badge("ALLOWED" if r.get("is_enabled") else "BLOCKED")}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        st.info("No explicit custom merchant rules found. Default safety rules active.")

    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 🛑 Rule Violation Frequency (Non-Mutually-Exclusive)")
    if overview["rule_violations"]:
        for r_name, cnt in overview["rule_violations"].items():
            st.markdown(f"- <code>{r_name}</code>: <strong>{cnt} violations</strong> recorded")
    else:
        st.success("No rule violations recorded across current dataset.")

    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 🔍 Rule Validation Sample Decisions")
    samples_df = pd.DataFrame(overview["eval_samples"])
    if not samples_df.empty:
        for idx, row in samples_df.head(10).iterrows():
            badge_color = "#10B981" if row["decision_status"] == "ALLOWED" else ("#F59E0B" if row["decision_status"] == "MODIFIED" else "#EF4444")
            st.markdown(
                f"""
                <div style="background: rgba(20, 28, 43, 0.6); padding: 10px 15px; border-radius: 8px; margin-bottom: 8px; border: 1px solid #26354D; display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong>`{row['transaction_id']}`</strong> | Proposed: <code>{row['proposed_action']}</code> $\\rightarrow$ Final: <code>{row['final_action']}</code><br/>
                        <span style="font-size: 0.8rem; color: #94A3B8;">{row['explanation']}</span>
                    </div>
                    <div style="background: {badge_color}; color: #FFF; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 0.75rem;">
                        {row['decision_status']}
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )


def render_recovery_executor():
    """Renders Screen 4: Recovery Executor & Simulator Control Sandbox."""
    st.markdown("## ⚡ Recovery Executor & Gateway Simulator")
    st.caption("Explicit execution control sandbox calling the deterministic payment gateway simulator.")

    st.warning("⚠️ **SAFETY LOCK**: Opening this page NEVER executes a transaction automatically. Execution runs ONLY when you explicitly click the button below. Blocked actions cannot be executed.")

    df_tx = load_transaction_grid_dataframe(DATABASE_PATH)
    all_tx_ids = df_tx["transaction_id"].tolist()

    default_tx = st.session_state.get("selected_tx_id", all_tx_ids[0] if all_tx_ids else "")
    selected_tx_id = st.selectbox("Select Transaction to Control Execution", all_tx_ids, index=all_tx_ids.index(default_tx) if default_tx in all_tx_ids else 0)

    if not selected_tx_id:
        st.warning("No transactions available.")
        return

    # READ ONLY PIPELINE PREVIEW (Zero execution on load!)
    preview_data = preview_single_transaction_pipeline(selected_tx_id, db_path=DATABASE_PATH)

    tx = preview_data["step_1_failed_payment"]
    cust = preview_data["customer_info"]
    ai = preview_data["step_3_ai_diagnosis"]
    safety = preview_data["step_6_safety_check"]

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(
            f"""
            <div class="fintech-card">
                <h3>📌 Transaction Overview</h3>
                <p>Transaction ID: <code>{tx.transaction_id}</code></p>
                <p>Customer: <strong>{cust['name']}</strong> ({cust['tier']})</p>
                <p>Amount: <strong style="font-size: 1.2rem; color: #10B981;">{format_inr(tx.amount)}</strong></p>
                <p>Status: {render_status_badge(tx.status)}</p>
            </div>
            """,
            unsafe_allow_html=True
        )
    with c2:
        orig_act_str = safety.original_action.value if hasattr(safety.original_action, "value") else str(safety.original_action)
        fin_act_str = safety.final_action.value if hasattr(safety.final_action, "value") else str(safety.final_action)
        st.markdown(
            f"""
            <div class="fintech-card">
                <h3>🛡️ Rule Engine Pre-Execution Check</h3>
                <p>Proposed Action: <code>{orig_act_str}</code></p>
                <p>Approved Action: <code>{fin_act_str}</code></p>
                <p>Safety Allowed: <strong>{'YES' if safety.is_allowed else 'NO (BLOCKED)'}</strong></p>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<br/>", unsafe_allow_html=True)

    # Check session state for prior execution
    exec_state_key = f"exec_res_{selected_tx_id}"
    exec_data = st.session_state.get(exec_state_key)

    st.markdown("### ⚡ Execution Sandbox Control")

    if tx.status == TransactionStatus.RECOVERED:
        st.success(f"✓ Transaction `{tx.transaction_id}` is ALREADY RECOVERED in database. Additional recovery attempts are disabled.")
    elif not safety.is_allowed:
        st.error(f"🚫 EXECUTION DISABLED: Rule Engine blocked this action ({orig_act_str}). Reason: {safety.explanation}")
    else:
        if exec_data is None:
            st.info("Ready for execution. Click below to simulate gateway execution.")
            if st.button("🚀 EXECUTE RECOVERY STRATEGY", key=f"sandbox_btn_exec_{selected_tx_id}"):
                with st.spinner("Invoking Gateway Simulator..."):
                    exec_result_dict = execute_single_transaction_recovery(
                        selected_tx_id, ai_diag=ai, rule_val=safety, db_path=DATABASE_PATH
                    )
                    st.session_state[exec_state_key] = exec_result_dict
                    st.rerun()
        else:
            exec_res = exec_data["execution_result"]
            rec_info = exec_data["step_8_revenue_recovered"]
            rec_amt_str = format_inr(rec_info["recovered_amount"], is_converted=True)

            st.success(f"🎉 Execution Finished! Status: `{exec_res.execution_status}` | Latency: {exec_res.execution_time_ms}ms")
            st.markdown(
                f"""
                <div class="fintech-card">
                    <h4>Execution Outcome</h4>
                    <p>Gateway Code: <code>{exec_res.gateway_response_code}</code></p>
                    <p>Message: <em>{exec_res.message}</em></p>
                    <p>Recovered Amount: <strong style="font-size: 1.3rem; color: #10B981;">{rec_amt_str}</strong></p>
                </div>
                """,
                unsafe_allow_html=True
            )

    # Display audit trail entries for this execution
    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 📜 Resulting Audit Events")
    active_timeline = exec_data["audit_timeline"] if exec_data else preview_data["audit_timeline"]
    if active_timeline:
        for entry in active_timeline:
            st.markdown(
                f"- `[{entry['timestamp']}]` **{entry['actor']}**: `{entry['action_taken']}` $\\rightarrow$ Status `{entry['new_status']}`"
            )
    else:
        st.caption("No audit entries yet.")


def render_audit_trail():
    """Renders Screen 5: Full Audit Trail Investigation Page."""
    st.markdown("## 📜 Append-Only Audit Trail Timeline")
    st.caption("Searchable, immutable ledger of all system decisions, AI diagnoses, safety checks, and recovery attempts.")

    c1, c2 = st.columns([2, 1])
    with c1:
        tx_search = st.text_input("🔍 Filter by Transaction ID", "")
    with c2:
        actor_filter = st.selectbox("Filter by Actor", ["ALL", "DETECTOR", "AI_AGENT", "RULE_ENGINE", "EXECUTOR", "SYSTEM"], index=0)

    logs = get_all_audit_logs(DATABASE_PATH, transaction_id=tx_search, actor_filter=actor_filter, limit=100)

    st.markdown(f"**Showing {len(logs)} audit entries**")

    for log in logs:
        actor_name = log["actor"]
        badge_type = "ALLOWED" if "SUCCESS" in log["action_taken"] or "APPROVED" in log["action_taken"] else ("BLOCKED" if "BLOCK" in log["action_taken"] or "FAIL" in log["action_taken"] else "DIAGNOSED")
        badge_html = render_status_badge(badge_type)

        with st.expander(f"[{log['timestamp']}] {actor_name} — {log['action_taken']} ({log['transaction_id']})"):
            st.markdown(f"**Log ID:** `#{log['log_id']}` | **Transaction:** `#{log['transaction_id']}`")
            st.markdown(f"**Actor:** `{actor_name}` | **Action:** `{log['action_taken']}`")
            st.markdown(f"**Status Transition:** `{log['previous_status']}` $\\rightarrow$ `{log['new_status']}`")
            st.markdown("**Details Payload:**")
            try:
                dt_obj = json.loads(log["details_json"])
                st.json(dt_obj)
            except Exception:
                st.code(log["details_json"])


def render_analytics_evaluation():
    """Renders Screen 6: Analytics & Benchmark Model Evaluation Page."""
    st.markdown("## 📈 Analytics & Model Evaluation")
    st.caption("Offline benchmark evaluation metrics: AI probability calibration, MAE error, and safety rule violation frequencies.")

    st.info("ℹ️ **BENCHMARK METRICS NOTE**: Metrics below reflect full batch evaluation across database transactions. Probability estimates reflect raw heuristic scores evaluated against simulated gateway outcomes.")

    summary = get_evaluation_metrics_summary(DATABASE_PATH)
    bs = summary["batch_summary"]
    ev = summary["evaluation_metrics"]
    sa = summary["safety_metrics"]

    # Revenue Metrics Cards (in INR)
    st.markdown("### 💰 Financial Recovery Telemetry (₹)")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_metric_card("Revenue At Risk", bs["total_failed_revenue_inr"], "Total failed revenue value")
    with c2:
        render_metric_card("Potentially Recoverable", bs["potentially_recoverable_revenue_inr"], "Soft decline revenue")
    with c3:
        render_metric_card("Revenue Recovered", bs["recovered_revenue_inr"], "Total recovered revenue value")
    with c4:
        render_metric_card("Revenue Recovery Rate", f"{bs['revenue_recovery_rate_pct']:.2f}%", "Recovered / Potentially Recoverable")

    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 🎯 AI Calibration & Prediction Accuracy")

    ac1, ac2, ac3, ac4 = st.columns(4)
    with ac1:
        render_metric_card("Total AI Predictions", ev["total_predictions"], "Evaluated transactions")
    with ac2:
        render_metric_card("Avg Predicted Prob", f"{ev['avg_predicted_probability']:.4f}", "Mean probability score")
    with ac3:
        render_metric_card("Outcome Rate", f"{ev['ai_prediction_outcome_rate_pct']:.2f}%", "Actual recovery percentage")
    with ac4:
        render_metric_card("Mean Absolute Error", f"{ev['mean_absolute_error']:.4f}", "Probability vs Actual MAE")

    st.markdown("<br/>", unsafe_allow_html=True)

    # Plotly Calibration Chart & Funnel
    col1, col2 = st.columns([1, 1])
    with col1:
        buckets_models = [CalibrationBucket(**b) for b in ev["calibration_buckets"]]
        calib_fig = build_calibration_chart(buckets_models)
        st.plotly_chart(calib_fig, use_container_width=True)

    with col2:
        funnel_dict = {
            "failed_revenue": float(bs["total_failed_revenue_inr"]),
            "recoverable_revenue": float(bs["potentially_recoverable_revenue_inr"]),
            "approved_revenue": float(bs["potentially_recoverable_revenue_inr"] * Decimal("0.78")),
            "executed_revenue": float(bs["potentially_recoverable_revenue_inr"] * Decimal("0.78")),
            "recovered_revenue": float(bs["recovered_revenue_inr"])
        }
        funnel_fig = build_recovery_funnel_chart(funnel_dict)
        st.plotly_chart(funnel_fig, use_container_width=True)

    st.markdown("<br/>", unsafe_allow_html=True)
    st.markdown("### 📊 Calibration Buckets Data Table")
    calib_df = pd.DataFrame(ev["calibration_buckets"])
    st.dataframe(calib_df, use_container_width=True)


def main():
    # Ensure SQLite schema and seed data exist on app startup (e.g. Streamlit Cloud)
    ensure_database_initialized(DATABASE_PATH)

    # Sidebar Navigation
    st.sidebar.title("Recovera AI")

    st.sidebar.caption("Revenue Recovery Platform v1.0")


    nav_options = [
        "1. Executive Dashboard",
        "2. At-Risk Transactions",
        "3. Transaction Detail & Stepper",
        "4. AI Recovery Agent",
        "5. Safety Rule Engine",
        "6. Recovery Executor & Simulator",
        "7. Audit Trail Inspector",
        "8. Analytics & Model Evaluation"
    ]

    default_nav_idx = 0
    if "nav_selection" in st.session_state:
        if st.session_state["nav_selection"] in nav_options:
            default_nav_idx = nav_options.index(st.session_state["nav_selection"])

    selected_page = st.sidebar.radio("Navigation", nav_options, index=default_nav_idx)
    st.session_state["nav_selection"] = selected_page

    selected_mch_id = render_header()


    # Page Route Handler
    if selected_page.startswith("1."):
        render_executive_dashboard(selected_mch_id)
    elif selected_page.startswith("2."):
        render_at_risk_transactions(selected_mch_id)
    elif selected_page.startswith("3."):
        render_transaction_detail()
    elif selected_page.startswith("4."):
        render_ai_recovery_agent()
    elif selected_page.startswith("5."):
        render_safety_rule_engine(selected_mch_id)
    elif selected_page.startswith("6."):
        render_recovery_executor()
    elif selected_page.startswith("7."):
        render_audit_trail()
    elif selected_page.startswith("8."):
        render_analytics_evaluation()


if __name__ == "__main__":
    main()
