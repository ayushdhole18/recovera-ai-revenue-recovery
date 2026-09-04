from decimal import Decimal
from typing import Optional, Any
import streamlit as st


def render_metric_card(title: str, value: Any, subtext: Optional[str] = None):
    """
    Renders a dark fintech metric card using custom HTML/CSS.
    Preserves exact monetary formatting.
    """
    if isinstance(value, Decimal):
        val_str = f"${value:,.2f}"
    elif isinstance(value, float):
        if value <= 1.0 and "Rate" not in title:
            val_str = f"{value:.4f}"
        else:
            val_str = f"{value:.2f}%"
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
