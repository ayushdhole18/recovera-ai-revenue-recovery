from typing import List, Optional
import streamlit as st
from app.components.status_badge import render_status_badge


def render_safety_banner(
    original_action: str,
    is_allowed: bool,
    final_action: str,
    violated_rules: List[str],
    explanation: str
):
    """
    Renders high-visibility Safety Guardrail Interception Banner for modified or blocked AI recommendations.
    """
    if is_allowed and original_action == final_action:
        banner_html = f"""
        <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.3); border-left: 4px solid #10B981; border-radius: 8px; padding: 14px 18px; margin: 12px 0;">
            <div style="font-weight: 700; color: #10B981; margin-bottom: 4px;">🛡️ SAFETY RULE CHECK PASSED</div>
            <div style="font-size: 0.85rem; color: #94A3B8;">Proposed action <code>{original_action}</code> fully complies with merchant business policies.</div>
        </div>
        """
    else:
        v_rules_str = ", ".join([f"<code>{r}</code>" for r in violated_rules]) if violated_rules else "None"
        badge_html = render_status_badge("BLOCKED" if not is_allowed else "MODIFIED")

        banner_html = f"""
        <div class="safety-banner">
            <div class="safety-banner-title">
                🛡️ SAFETY RULE INTERCEPTION {badge_html}
            </div>
            <div style="font-size: 0.88rem; color: #F8FAFC; margin-bottom: 6px;">
                <strong>Original AI Proposal:</strong> <code>{original_action}</code>
            </div>
            <div style="font-size: 0.88rem; color: #F8FAFC; margin-bottom: 6px;">
                <strong>Violated Safety Rules:</strong> {v_rules_str}
            </div>
            <div style="font-size: 0.88rem; color: #94A3B8; margin-bottom: 8px;">
                <strong>Merchant Policy Decision:</strong> {explanation}
            </div>
            <div style="font-size: 0.9rem; font-weight: 700; color: #F8FAFC;">
                <strong>Final Safety Outcome Executed:</strong> <code>{final_action}</code>
            </div>
        </div>
        """

    st.markdown(banner_html, unsafe_allow_html=True)
