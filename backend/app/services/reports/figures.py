"""Figuras de reporte a 600 DPI (PNG) con matplotlib, para Word. El PDF usa SVG vectorial (sin pérdida a cualquier zoom)."""

import io

from app.services.reports.model import Chart

DPI = 600
COLORS = ("#1d5bb8", "#b3261e", "#8a5300")


def line_chart_png(chart: Chart, dpi: int = DPI) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.6, 2.7))
    xs = list(range(len(chart.labels)))
    for i, (name, vals) in enumerate(chart.series):
        ax.plot(xs, vals, color=COLORS[i % len(COLORS)], linewidth=1.6, label=name)
    step = max(1, len(xs) // 6)
    ticks = sorted({*xs[::step], xs[-1]}) if xs else []
    ax.set_xticks(ticks, [chart.labels[i] for i in ticks], fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    ax.set_ylim(bottom=0)
    ax.set_title(chart.title, fontsize=9, loc="left")
    ax.grid(axis="y", color="#e3e3dc", linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(fontsize=7, frameon=False, loc="upper right")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()
