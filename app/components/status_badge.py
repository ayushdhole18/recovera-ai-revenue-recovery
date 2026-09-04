import streamlit as st


def render_status_badge(status_str: str) -> str:
    """
    Returns HTML string for a semantic status badge pill.
    Status types: ALLOWED, MODIFIED, BLOCKED, FALLBACK, RECOVERED, SOFT_FAILED, HARD_FAILED, MANUAL_REVIEW
    """
    st_upper = str(status_str).upper()

    if st_upper in ["ALLOWED", "RECOVERED", "SUCCESS"]:
        css_class = "badge-pill-success"
        label = f"✓ {st_upper}"
    elif st_upper in ["BLOCKED", "HARD_FAILED", "REJECTED"]:
        css_class = "badge-pill-danger"
        label = f"✕ {st_upper}"
    elif st_upper in ["MODIFIED", "FALLBACK", "SOFT_FAILED", "WARNING"]:
        css_class = "badge-pill-fallback"
        label = f"⚠ {st_upper}"
    else:
        css_class = "badge-pill-live"
        label = f"ℹ {st_upper}"

    return f'<span class="badge-pill {css_class}">{label}</span>'
