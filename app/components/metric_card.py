from decimal import Decimal
from typing import Optional, Any
import streamlit as st
from app.utils.currency import format_inr


def render_metric_card(title: str, value: Any, subtext: Optional[str] = None):
    """
    Renders a dark fintech metric card using custom HTML/CSS.
    Preserves exact monetary formatting in INR (₹).
    """
    if isinstance(value, Decimal):
        val_str = format_inr(value, is_converted=True)
    elif isinstance(value, float):
        if "Rate" in title or "pct" in title.lower():
            val_str = f"{value:.2f}%"
        elif value <= 1.0:
            val_str = f"{value:.4f}"
        else:
            val_str = format_inr(value, is_converted=True)
    else:
        val_str = str(value)

    sub_html = f'<div class="metric-subtext">{subtext}</div>' if subtext else ""

    card_html = f"""
    <div class="fintech-card">
        <div class="metric-title">{title}</div>
        <div class="metric-value">{val_str}</div>
        {sub_html}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

