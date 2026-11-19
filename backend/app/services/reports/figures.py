"""Figuras de reporte a 600 DPI (PNG) con matplotlib, para Word. El PDF usa SVG vectorial (sin pérdida a cualquier zoom)."""

import io
from typing import Any

from app.services.reports.model import Chart

DPI = 600
COLORS = ("#1d5bb8", "#b3261e", "#8a5300")
# Curvas XY: se distinguen por trazo además de por color (legibles también en blanco y negro).
XY_STYLES: tuple[tuple[str, Any, float], ...] = (("#1d5bb8", "-", 1.8), ("#1b1c1a", (0, (5, 2)), 1.4), ("#6e6e73", (0, (1, 2)), 1.6))


def _plt() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _finish(fig: Any, ax: Any, title: str, dpi: int) -> bytes:
    ax.set_title(title, fontsize=9, loc="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    _plt().close(fig)
    return buf.getvalue()


def line_chart_png(chart: Chart, dpi: int = DPI) -> bytes:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.6, 2.7))
    xs = list(range(len(chart.labels)))
    for i, (name, vals) in enumerate(chart.series):
        ax.plot(xs, vals, color=COLORS[i % len(COLORS)], linewidth=1.6, label=name)
    step = max(1, len(xs) // 6)
    ticks = sorted({*xs[::step], xs[-1]}) if xs else []
    ax.set_xticks(ticks, [chart.labels[i] for i in ticks], fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#e3e3dc", linewidth=0.6)
    ax.legend(fontsize=7, frameon=False, loc="upper right")
    return _finish(fig, ax, chart.title, dpi)


def bar_chart_png(chart: Chart, dpi: int = DPI) -> bytes:
    """Barras horizontales: una por tramo, con el conteo al final de cada barra."""
    plt = _plt()
    vals = chart.series[0][1] if chart.series else []
    fig, ax = plt.subplots(figsize=(6.6, 0.32 * len(vals) + 0.8))
    ys = list(range(len(vals)))[::-1]  # el primer tramo arriba
    ax.barh(ys, vals, color=COLORS[0], height=0.6)
    ax.set_yticks(ys, chart.labels, fontsize=7)
    ax.tick_params(axis="x", labelsize=7)
    top = max([1.0, *vals])
    for y, v in zip(ys, vals, strict=True):
        ax.text(v + top * 0.01, y, f"{v:.0f}", va="center", fontsize=7)
    ax.set_xlim(0, top * 1.1)
    ax.set_xlabel(chart.x_label or "Hallazgos", fontsize=7)
    ax.grid(axis="x", color="#e3e3dc", linewidth=0.6)
    return _finish(fig, ax, chart.title, dpi)


def xy_chart_png(chart: Chart, dpi: int = DPI) -> bytes:
    """Curvas en [0, 1] (ROC o precisión-cobertura) con su referencia: diagonal del azar o línea base."""
    plt = _plt()
    fig, ax = plt.subplots(figsize=(4.6, 3.6))
    if chart.ref == "diagonal":
        ax.plot([0, 1], [0, 1], color="#aaaaaa", linewidth=0.8, linestyle=(0, (3, 3)), label="Azar")
    elif chart.ref.startswith("h:"):
        b = float(chart.ref[2:])
        ax.axhline(b, color="#aaaaaa", linewidth=0.8, linestyle=(0, (3, 3)), label=f"Línea base ({b * 100:.0f} %)")
    for i, (name, pts) in enumerate(chart.xy):
        color, dash, width = XY_STYLES[i % len(XY_STYLES)]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=color, linestyle=dash, linewidth=width, label=name,
                drawstyle="steps-post" if chart.ref.startswith("h:") else "default")  # fmt: skip
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ticks = [0, 0.25, 0.5, 0.75, 1]
    ax.set_xticks(ticks, [f"{t * 100:.0f} %" for t in ticks], fontsize=7)
    ax.set_yticks(ticks, [f"{t * 100:.0f} %" for t in ticks], fontsize=7)
    ax.set_xlabel(chart.x_label, fontsize=7)
    ax.set_ylabel(chart.y_label, fontsize=7)
    ax.grid(color="#e3e3dc", linewidth=0.6)
    ax.legend(fontsize=6.5, frameon=False, loc="lower right")
    return _finish(fig, ax, chart.title, dpi)


def chart_png(chart: Chart, dpi: int = DPI) -> bytes:
    return {"bar": bar_chart_png, "xy": xy_chart_png}.get(chart.kind, line_chart_png)(chart, dpi)
