"""PDF con WeasyPrint. Jinja2 con autoescape: el texto de fuentes externas (nombres de CVE, descripciones) nunca se
interpreta como HTML."""

from jinja2 import Environment, select_autoescape

from app.services.reports.model import Chart, Report, risk_suffix

_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_env.globals['risk_suffix'] = risk_suffix

TEMPLATE = _env.from_string(
    """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>{{ r.title }}</title>
<style>
  @page { size: {{ 'A4 landscape' if r.wide else 'A4' }}; margin: 16mm 14mm 16mm 14mm;
          @bottom-left { content: "Radar KEV/EPSS · {{ r.title }}"; font-size: 8px; color: #666; }
          @bottom-right { content: "Página " counter(page) " de " counter(pages); font-size: 8px; color: #666; } }
  body { font-family: "DejaVu Sans", sans-serif; font-size: 9.5px; color: #1b1c1a; line-height: 1.4; }
  h1 { font-size: 19px; margin: 0 0 2px 0; } h2 { font-size: 12px; margin: 16px 0 5px 0; border-bottom: 1px solid #c9c9c1; padding-bottom: 2px; }
  .sub { color: #555; margin-bottom: 3px; } .meta { color: #777; font-size: 8px; margin-bottom: 10px; }
  .kpis { display: flex; gap: 22px; margin: 8px 0 4px 0; } .kpi b { display: block; font-size: 20px; line-height: 1.1; } .kpi span { color: #555; font-size: 8px; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; } th { text-align: left; font-size: 8px; color: #444; border-bottom: 1.2px solid #1b1c1a; padding: 3px 4px; }
  td { padding: 3px 4px; border-bottom: .5px solid #d6d6cf; vertical-align: top; overflow-wrap: anywhere; } td.r, th.r { text-align: right; }
  tr { page-break-inside: avoid; } .note { color: #666; font-size: 8px; margin-top: 3px; }
  .ai { border: 1px solid #bbb; border-left: 3px solid #1d5bb8; padding: 6px 9px; margin: 10px 0; background: #f6f6f3; }
  .ai .badge { font-size: 8px; font-weight: bold; color: #1d5bb8; } .ai ul { margin: 2px 0 4px 14px; padding: 0; }
  .how { border-left: 3px solid #86868b; background: #f6f6f3; padding: 4px 8px; margin-top: 5px; font-size: 8.5px; color: #333; }
  .warn { color: #8a5300; font-size: 8.5px; margin: 6px 0; }
</style></head><body>
<h1>{{ r.title }}</h1><div class="sub">{{ r.subtitle }}</div>
<div class="meta">Generado el {{ r.generated_at.strftime('%d/%m/%Y %H:%M') }} UTC · Radar de explotación activa (KEV/EPSS)</div>
{% if r.kpis %}<div class="kpis">{% for label, value in r.kpis %}<div class="kpi"><b>{{ value }}</b><span>{{ label }}</span></div>{% endfor %}</div>{% endif %}
{% if r.ai %}<div class="ai"><div class="badge">✦ GENERADO POR IA · {{ r.ai.provider }}/{{ r.ai.model }} · {{ r.ai.generated_at[:10] }}</div>
  <h2 style="border:0;margin:4px 0 2px 0">Resumen ejecutivo</h2><p style="margin:0 0 4px 0">{{ r.ai.summary.tendencia }}</p>
  <b>Riesgos principales</b><ul>{% for x in r.ai.summary.riesgos_principales %}<li>{{ x.texto }}<i>{{ risk_suffix(x.texto, x.cve_ids) }}</i></li>{% endfor %}</ul>
  <b>Recomendaciones</b><ul>{% for x in r.ai.summary.recomendaciones %}<li>{{ x }}</li>{% endfor %}</ul>
  <div class="note">Texto redactado por un modelo de lenguaje a partir de las cifras de este radar; revíselo antes de difundirlo.</div></div>{% endif %}
{% for n in r.notes %}<div class="warn">{{ n }}</div>{% endfor %}
{% if chart_svg %}<h2>{{ r.chart.title }}</h2>{{ chart_svg | safe }}{% if r.chart.how_to_read %}<div class="how"><b>Cómo leerlo.</b> {{ r.chart.how_to_read }}</div>{% endif %}{% endif %}
{% for t in r.tables %}<h2>{{ t.title }}</h2>
{% if t.rows %}<table><thead><tr>{% for c in t.columns %}<th class="{{ 'r' if loop.index0 in t.right else '' }}">{{ c }}</th>{% endfor %}</tr></thead>
<tbody>{% for row in t.rows %}<tr>{% for cell in row %}<td class="{{ 'r' if loop.index0 in t.right else '' }}">{{ cell }}</td>{% endfor %}</tr>{% endfor %}</tbody></table>
{% else %}<div class="note">Sin datos.</div>{% endif %}{% if t.how_to_read %}<div class="how"><b>Cómo leerla.</b> {{ t.how_to_read }}</div>{% endif %}{% if t.note %}<div class="note">{{ t.note }}</div>{% endif %}{% endfor %}
</body></html>"""
)


def line_chart_svg(chart: Chart, width: int = 640, height: int = 170) -> str:
    """Gráfico de líneas en SVG puro (sin dependencias); los textos se escapan al construirlo."""
    from html import escape

    pad_l, pad_r, pad_t, pad_b = 34, 10, 10, 22
    n = len(chart.labels)
    top = max([1.0] + [v for _, vals in chart.series for v in vals])
    colors = ["#1d5bb8", "#b3261e", "#8a5300"]

    def x(i: float) -> float:
        return pad_l + (width - pad_l - pad_r) * (i / max(1, n - 1))

    def y(v: float) -> float:
        return pad_t + (height - pad_t - pad_b) * (1 - v / top)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="DejaVu Sans" font-size="8">']
    for k in range(1, 5):  # sin la etiqueta "0": se pisaría con las fechas del eje X
        v = top * k / 4
        parts.append(f'<line x1="{pad_l}" x2="{width - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e3e3dc" stroke-width=".6"/>'
                     f'<text x="{pad_l - 4}" y="{y(v) + 3:.1f}" text-anchor="end" fill="#666">{v:.0f}</text>')
    for s, (name, vals) in enumerate(chart.series):
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
        parts.append(f'<polyline fill="none" stroke="{colors[s % 3]}" stroke-width="1.6" points="{pts}"/>')
        parts.append(f'<text x="{pad_l + 6 + s * 110}" y="{height - 4}" fill="{colors[s % 3]}">● {escape(name)}</text>')
    for i in sorted({0, n // 2, n - 1}):
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"  # los extremos no se salen del lienzo
        parts.append(f'<text x="{x(i):.1f}" y="{height - 14}" text-anchor="{anchor}" fill="#666">{escape(chart.labels[i])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def render(report: Report) -> bytes:
    from weasyprint import HTML

    svg = line_chart_svg(report.chart) if report.chart and report.chart.labels else ""
    html = TEMPLATE.render(r=report, chart_svg=svg)
    return bytes(HTML(string=html).write_pdf())
