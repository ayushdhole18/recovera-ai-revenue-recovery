from typing import List, Dict, Any
import plotly.graph_objects as go
import plotly.express as px
from app.core.models import RevenueBreakdownItem, ActionPerformanceItem, CalibrationBucket


def apply_dark_fintech_layout(fig: go.Figure, title_text: str) -> go.Figure:
    """
    Applies consistent dark fintech styling layout to Plotly charts.
    """
    fig.update_layout(
        title=dict(
            text=f"<b>{title_text}</b>",
            font=dict(family="Inter, sans-serif", size=14, color="#F8FAFC")
        ),
        paper_bgcolor="rgba(20, 28, 43, 0.6)",
        plot_bgcolor="rgba(11, 15, 23, 0.4)",
        font=dict(family="Inter, sans-serif", color="#94A3B8", size=12),
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis=dict(
            gridcolor="#26354D",
            zerolinecolor="#26354D",
            showline=True,
            linecolor="#26354D"
        ),
        yaxis=dict(
            gridcolor="#26354D",
            zerolinecolor="#26354D",
            showline=True,
            linecolor="#26354D"
        ),
        legend=dict(
            font=dict(color="#F8FAFC"),
            bgcolor="rgba(20, 28, 43, 0.8)",
            bordercolor="#26354D"
        )
    )
    return fig


def build_recovery_funnel_chart(funnel_data: Dict[str, float]) -> go.Figure:
    """
    Builds a Plotly Funnel Chart for Revenue Recovery Stages.
    """
    stages = [
        "1. Failed Revenue (At Risk)",
        "2. Potentially Recoverable",
        "3. Approved Strategy",
        "4. Executed Strategy",
        "5. Revenue Recovered"
    ]
    values = [
        funnel_data.get("failed_revenue", 0.0),
        funnel_data.get("recoverable_revenue", 0.0),
        funnel_data.get("approved_revenue", 0.0),
        funnel_data.get("executed_revenue", 0.0),
        funnel_data.get("recovered_revenue", 0.0)
    ]

    fig = go.Figure(go.Funnel(
        y=stages,
        x=values,
        textinfo="value+percent initial",
        marker=dict(color=["#EF4444", "#F59E0B", "#3B82F6", "#6366F1", "#10B981"]),
        connector=dict(line=dict(color="#26354D", width=1))
    ))
    return apply_dark_fintech_layout(fig, "End-to-End Revenue Recovery Funnel ($)")


def build_revenue_leakage_chart(leakage_items: List[RevenueBreakdownItem]) -> go.Figure:
    """
    Builds a horizontal bar chart of Revenue Leakage by Category/Failure Reason.
    """
    categories = [item.category_key for item in leakage_items]
    failed_rev = [float(item.failed_revenue) for item in leakage_items]
    recovered_rev = [float(item.recovered_revenue) for item in leakage_items]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=categories,
        x=failed_rev,
        name="Failed Revenue",
        orientation="h",
        marker_color="#EF4444"
    ))
    fig.add_trace(go.Bar(
        y=categories,
        x=recovered_rev,
        name="Recovered Revenue",
        orientation="h",
        marker_color="#10B981"
    ))

    fig.update_layout(barmode="group")
    return apply_dark_fintech_layout(fig, "Revenue Leakage & Recovery by Failure Reason ($)")


def build_action_performance_chart(action_items: List[ActionPerformanceItem]) -> go.Figure:
    """
    Builds a grouped bar chart of Recovery Action Performance.
    """
    actions = [item.action for item in action_items]
    recommended = [item.number_recommended for item in action_items]
    approved = [item.number_approved for item in action_items]
    executed = [item.number_executed for item in action_items]
    successful = [item.successful_recoveries for item in action_items]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=actions, y=recommended, name="Recommended", marker_color="#6366F1"))
    fig.add_trace(go.Bar(x=actions, y=approved, name="Approved", marker_color="#3B82F6"))
    fig.add_trace(go.Bar(x=actions, y=executed, name="Executed", marker_color="#F59E0B"))
    fig.add_trace(go.Bar(x=actions, y=successful, name="Recovered", marker_color="#10B981"))

    fig.update_layout(barmode="group")
    return apply_dark_fintech_layout(fig, "Recovery Action Performance Breakdown")


def build_calibration_chart(calibration_buckets: List[CalibrationBucket]) -> go.Figure:
    """
    Builds a grouped bar chart comparing AI Predicted Probability vs Actual Recovery Rate across calibration buckets.
    """
    buckets = [b.bucket_label for b in calibration_buckets]
    pred_prob = [b.avg_predicted_probability * 100.0 for b in calibration_buckets]
    actual_rate = [b.actual_recovery_rate_pct for b in calibration_buckets]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=buckets, y=pred_prob, name="Avg Predicted Prob (%)", marker_color="#6366F1"))
    fig.add_trace(go.Bar(x=buckets, y=actual_rate, name="Actual Recovery Rate (%)", marker_color="#10B981"))

    fig.update_layout(barmode="group")
    return apply_dark_fintech_layout(fig, "AI Probability Calibration vs Actual Outcome")
