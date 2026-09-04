import os
import sys
from pathlib import Path
from decimal import Decimal
import streamlit as st
import pandas as pd

# Add project root directory to sys.path for clean imports
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from app.config import DATABASE_PATH
from app.core.models import TransactionStatus
from app.services.ui_helpers import (
    get_merchant_dropdown_options, load_transaction_grid_dataframe,
    get_dashboard_analytics_summary, preview_single_transaction_pipeline,
    execute_single_transaction_recovery
)
from app.components.metric_card import render_metric_card
from app.components.status_badge import render_status_badge
from app.components.safety_banner import render_safety_banner
from app.components.workflow_stepper import render_workflow_stepper
from app.components.charts import (
    build_recovery_funnel_chart, build_revenue_leakage_chart,
    build_action_performance_chart
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

    # 1. Hero Financial Metric Cards
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
    """Renders Page 2: At-Risk Transactions Grid."""
    st.markdown("## ⚠️ At-Risk Transactions Workspace")
    st.caption("Search, filter, and inspect failed payments requiring recovery intervention.")

    c1, c2 = st.columns([2, 1])
    with c1:
        search_query = st.text_input("🔍 Search by Transaction ID, Customer, or Email", "")
    with c2:
        status_filter = st.selectbox("Status Filter", ["ALL", "FAILED", "RECOVERED", "UNRECOVERABLE"], index=0)

    df = load_transaction_grid_dataframe(DATABASE_PATH, merchant_id=merchant_id, status_filter=status_filter)

    if search_query:
        mask = (
            df["transaction_id"].str.contains(search_query, case=False, na=False) |
            df["customer_name"].str.contains(search_query, case=False, na=False) |
            df["merchant_name"].str.contains(search_query, case=False, na=False)
        )
        df = df[mask]

    st.markdown(f"**Showing {len(df)} transactions**")

    # Display grid with action buttons
    for idx, row in df.head(15).iterrows():
        tx_id = row["transaction_id"]
        amt_str = row["amount_formatted"]
        reason = row["failure_reason"]
        category = row["decline_category"]
        status = row["status"]

        with st.container():
            col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])
            with col1:
                st.markdown(f"**`{tx_id}`**")
                st.caption(f"{row['customer_name']} ({row['subscription_tier']})")
            with col2:
                st.markdown(f"**{amt_str}**")
                st.caption(f"{row['payment_method_type']} - {row['card_brand']}")
            with col3:
                st.markdown(f"<code>{reason}</code>", unsafe_allow_html=True)
                st.caption(f"Cat: {category}")
            with col4:
                st.markdown(render_status_badge(status), unsafe_allow_html=True)
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
                        <div style="font-size: 1.4rem; font-weight: 700; color: #10B981;">${tx.amount:,.2f} {tx.currency}</div>
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
                Amount: <strong>${tx.amount:,.2f} {tx.currency}</strong> | Failure Reason: <code>{tx.failure_reason}</code><br/>
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
        st.markdown(f'<div style="font-size: 1.2rem; font-weight: 700; color: #10B981;">🎉 REVENUE RECOVERED: ${rec_amt:,.2f}</div>', unsafe_allow_html=True)
    elif tx.status == TransactionStatus.RECOVERED:
        st.markdown(f'<div style="font-size: 1.2rem; font-weight: 700; color: #10B981;">🎉 REVENUE RECOVERED: ${tx.amount:,.2f}</div>', unsafe_allow_html=True)
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


def main():
    # Sidebar Navigation
    st.sidebar.image("https://img.icons8.com/isometric-folders/100/lightning-bolt.png", width=48)
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

    st.sidebar.markdown("---")
    st.sidebar.info("💡 **Hackathon Ready**: Append-only SQLite Audit Trail & Gemini Diagnostic Agent active.")

    selected_mch_id = render_header()

    # Page Route Handler
    if selected_page.startswith("1."):
        render_executive_dashboard(selected_mch_id)
    elif selected_page.startswith("2."):
        render_at_risk_transactions(selected_mch_id)
    elif selected_page.startswith("3."):
        render_transaction_detail()
    elif selected_page.startswith("4."):
        st.subheader("🧠 AI Recovery Agent")
        st.info("Phase 6D target: Gemini prompt inspector and live diagnostic playground.")
    elif selected_page.startswith("5."):
        st.subheader("🛡️ Safety Rule Engine")
        st.info("Phase 6D target: Merchant rule configuration and violation audit statistics.")
    elif selected_page.startswith("6."):
        st.subheader("⚡ Recovery Executor & Simulator")
        st.info("Phase 6D target: Gateway simulator trial execution sandbox.")
    elif selected_page.startswith("7."):
        st.subheader("📜 Audit Trail Inspector")
        st.info("Phase 6D target: Immutability timeline reconstruction & JSON log inspector.")
    elif selected_page.startswith("8."):
        st.subheader("📈 Analytics & Model Evaluation")
        st.info("Phase 6D target: MAE accuracy, calibration buckets, and evaluation report download.")


if __name__ == "__main__":
    main()
