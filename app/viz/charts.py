"""Interactive Plotly chart builders for Apex Margin Advisor."""
from __future__ import annotations

import plotly.graph_objects as go

EMERALD = "#065F46"
ROYAL = "#1E3A8A"
SKY = "#0284C7"
AMBER = "#D97706"
CRIMSON = "#B91C1C"
SLATE = "#64748B"
NAVY = "#0B1F3A"

PALETTE = [EMERALD, ROYAL, SKY, AMBER, SLATE]
STACK_PALETTE = [CRIMSON, AMBER, ROYAL, SLATE]


def figure(spec: dict | None) -> go.Figure | None:
    if not spec or not spec.get("kind"):
        return None
    kind = spec["kind"]
    title = spec.get("title", "")

    if kind == "stacked_hbar":
        ys = list(reversed(spec.get("y", [])))
        fig = go.Figure()
        for idx, s in enumerate(spec.get("series", [])):
            vals = list(reversed(s.get("values", [])))
            sname = s.get("name", f"Factor {idx + 1}")
            fig.add_trace(go.Bar(
                y=ys,
                x=vals,
                name=sname,
                orientation="h",
                marker_color=STACK_PALETTE[idx % len(STACK_PALETTE)],
                hovertemplate=f"{sname} — %{{y}}: %{{x:.1f}} pts<extra></extra>",
            ))
        fig.update_layout(
            barmode="stack",
            title={"text": title, "font": {"size": 15, "color": NAVY}},
            xaxis={"title": spec.get("x_label", "Points"), "range": [0, 105]},
            yaxis={"automargin": True},
            template="plotly_white",
            height=max(290, 95 + 48 * len(ys)),
            margin={"l": 24, "r": 24, "t": 52, "b": 32},
            legend={"orientation": "h", "y": -0.24},
        )
        return fig

    if kind == "hbar":
        xs = list(reversed(spec.get("x", [])))
        ys = list(reversed(spec.get("y", [])))
        colors = [CRIMSON if (v is not None and v < 0) else (AMBER if (spec.get("threshold") and v < spec["threshold"]) else EMERALD) for v in xs]
        fig = go.Figure(go.Bar(
            x=xs,
            y=ys,
            orientation="h",
            marker_color=colors,
            hovertemplate="%{y}: %{x:,.1f}<extra></extra>",
        ))
        if spec.get("threshold") is not None:
            fig.add_vline(
                x=spec["threshold"],
                line_dash="dash",
                line_color=CRIMSON,
                annotation_text=f"Min Threshold ({spec['threshold']:.0f}%)",
                annotation_position="top right",
            )
        fig.update_layout(
            title={"text": title, "font": {"size": 15, "color": NAVY}},
            xaxis={"title": spec.get("x_label", "Value")},
            yaxis={"automargin": True},
            template="plotly_white",
            height=max(290, 80 + 38 * len(ys)),
            margin={"l": 24, "r": 28, "t": 52, "b": 28},
        )
        return fig

    if kind == "grouped_bar":
        xs = spec.get("x", [])
        fig = go.Figure()
        for idx, s in enumerate(spec.get("series", [])):
            vals = s.get("values", [])
            sname = s.get("name", f"Series {idx + 1}")
            fig.add_trace(go.Bar(
                x=xs,
                y=vals,
                name=sname,
                marker_color=PALETTE[idx % len(PALETTE)],
                hovertemplate=f"{sname} — %{{x}}: $%{{y:,.0f}}<extra></extra>",
            ))
        fig.update_layout(
            barmode="group",
            title={"text": title, "font": {"size": 15, "color": NAVY}},
            yaxis={"title": spec.get("y_label", "USD ($)")},
            template="plotly_white",
            height=380,
            margin={"l": 24, "r": 24, "t": 52, "b": 32},
            legend={"orientation": "h", "y": -0.22},
        )
        return fig

    if kind == "bar":
        xs = spec.get("x", [])
        ys = spec.get("y", [])
        colors = [CRIMSON if v < 0 else (AMBER if "Cost" in x or "Expense" in x else EMERALD) for x, v in zip(xs, ys)]
        fig = go.Figure(go.Bar(
            x=xs,
            y=ys,
            marker_color=colors,
            hovertemplate="%{x}: $%{y:,.0f}<extra></extra>",
        ))
        fig.update_layout(
            title={"text": title, "font": {"size": 15, "color": NAVY}},
            yaxis={"title": spec.get("y_label", "USD ($)")},
            template="plotly_white",
            height=340,
            margin={"l": 24, "r": 24, "t": 52, "b": 28},
        )
        return fig

    return None
