from typing import Dict, Any
import streamlit as st
from app.components.status_badge import render_status_badge
from app.components.safety_banner import render_safety_banner


def render_workflow_stepper(pipeline_data: Dict[str, Any]):
    """
    Renders the 8-step visual recovery workflow stepper component.
    """
    tx = pipeline_data["step_1_failed_payment"]
    det = pipeline_data["step_2_recovery_detector"]
    ai = pipeline_data["step_3_ai_diagnosis"]
    prob_info = pipeline_data["step_4_recovery_probability"]
    rec_info = pipeline_data["step_5_recommended_action"]
    safety = pipeline_data["step_6_safety_check"]
    exec_res = pipeline_data["step_7_execution_result"]
    rev_info = pipeline_data["step_8_revenue_recovered"]

    st.markdown('<div class="stepper-container">', unsafe_allow_html=True)

    # Step 1: Failed Payment
    s1_html = f"""
    <div class="stepper-item">
        <div class="stepper-number">1</div>
        <div class="stepper-content">
            <div class="stepper-title">PAYMENT FAILED — Transaction Metadata</div>
            <div class="stepper-body">
                Transaction ID: <code>{tx.transaction_id}</code> | Amount: <strong>${tx.amount:,.2f} {tx.currency}</strong><br/>
                Customer: <code>{tx.customer_id}</code> | Failure Reason: <code>{tx.failure_reason}</code> | Method: {tx.payment_method_type} ({tx.card_brand})
            </div>
        </div>
    </div>
    """
    st.markdown(s1_html, unsafe_allow_html=True)

    # Step 2: Recovery Detector
    det_badge = render_status_badge("RECOVERABLE" if det.is_recoverable else "UNRECOVERABLE")
    s2_html = f"""
    <div class="stepper-item">
        <div class="stepper-number">2</div>
        <div class="stepper-content">
            <div class="stepper-title">RECOVERY DETECTOR — Recoverability Classification {det_badge}</div>
            <div class="stepper-body">
                Decline Category: <code>{det.decline_category}</code><br/>
                Next Step Recommendation: {det.recommended_next_step}
            </div>
        </div>
    </div>
    """
    st.markdown(s2_html, unsafe_allow_html=True)

    # Step 3: AI Diagnosis
    fb_badge = render_status_badge("FALLBACK" if ai.is_fallback else "GEMINI LIVE")
    s3_html = f"""
    <div class="stepper-item">
        <div class="stepper-number">3</div>
        <div class="stepper-content">
            <div class="stepper-title">AI DIAGNOSIS AGENT — Root Cause Diagnosis {fb_badge}</div>
            <div class="stepper-body">
                <strong>Diagnosis:</strong> {ai.failure_diagnosis}<br/>
                <strong>AI Reasoning:</strong> {ai.reasoning}<br/>
                <strong>Customer Draft:</strong> <em>"{ai.customer_message_draft or 'N/A'}"</em>
            </div>
        </div>
    </div>
    """
    st.markdown(s3_html, unsafe_allow_html=True)

    # Step 4: Recovery Probability
    s4_html = f"""
    <div class="stepper-item">
        <div class="stepper-number">4</div>
        <div class="stepper-content">
            <div class="stepper-title">RECOVERY PROBABILITY — Score Calibration</div>
            <div class="stepper-body">
                Estimated Probability Score: <strong>{prob_info['probability']:.2f}</strong> (Calibration Bucket: <code>{prob_info['bucket']}</code>)<br/>
                AI Confidence Score: {prob_info['confidence']:.2f}
            </div>
        </div>
    </div>
    """
    st.markdown(s4_html, unsafe_allow_html=True)

    # Step 5: Recommended Action
    s5_html = f"""
    <div class="stepper-item">
        <div class="stepper-number">5</div>
        <div class="stepper-content">
            <div class="stepper-title">RECOMMENDED ACTION — Strategy Proposal</div>
            <div class="stepper-body">
                Proposed Action: <code>{rec_info['proposed_action']}</code><br/>
                Recommended Retry Delay: {rec_info['retry_delay_hours']} hours
            </div>
        </div>
    </div>
    """
    st.markdown(s5_html, unsafe_allow_html=True)

    # Step 6: Safety Check
    st.markdown('<div class="stepper-item"><div class="stepper-number">6</div><div class="stepper-content"><div class="stepper-title">SAFETY CHECK — Rule Engine Validation</div>', unsafe_allow_html=True)
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

    # Step 7: Execution Result
    s7_badge = render_status_badge(exec_res.execution_status)
    s7_html = f"""
    <div class="stepper-item">
        <div class="stepper-number">7</div>
        <div class="stepper-content">
            <div class="stepper-title">EXECUTION RESULT — Payment Gateway Simulator {s7_badge}</div>
            <div class="stepper-body">
                Gateway Code: <code>{exec_res.gateway_response_code}</code> | Simulated Latency: {exec_res.execution_time_ms} ms<br/>
                Log Message: {exec_res.message}
            </div>
        </div>
    </div>
    """
    st.markdown(s7_html, unsafe_allow_html=True)

    # Step 8: Revenue Recovered
    s8_badge = render_status_badge("RECOVERED" if rev_info['is_success'] else "UNRECOVERED")
    s8_html = f"""
    <div class="stepper-item">
        <div class="stepper-number">8</div>
        <div class="stepper-content">
            <div class="stepper-title">REVENUE RECOVERED — Metric Impact {s8_badge}</div>
            <div class="stepper-body">
                Recovered Amount: <strong>${rev_info['recovered_amount']:,.2f}</strong><br/>
                Final Execution Status: <code>{rev_info['status']}</code>
            </div>
        </div>
    </div>
    """
    st.markdown(s8_html, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)
