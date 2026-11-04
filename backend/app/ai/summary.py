"""Resumen ejecutivo para los reportes de gestión. La IA redacta sobre cifras YA calculadas (services/stats.py)."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.ai import grounding, providers
from app.ai.audit import tracked
from app.ai.enrichment import Ungrounded, system_prompt
from app.ai.schemas import ExecutiveSummary
from app.services import stats

PROMPTS = Path(__file__).parent / "prompts"


def _context(a: dict[str, Any]) -> str:
    keep = ("open_kev", "new_kev_24h", "new_kev_7d", "sla_overdue", "sla_due_soon", "sla_overdue_kev", "active_total", "by_band",
            "kev_by_asset_criticality", "kev_epss_distribution", "mttr_days", "sla_compliance_pct", "resolved_90d")  # fmt: skip
    lines = ["Indicadores:"] + [f"- {k}: {json.dumps(a[k], ensure_ascii=False)}" for k in keep]
    lines.append("Tendencia (últimos días, kev_open / sla_overdue):")
    lines += [f"- {t['date']}: {t['kev_open']} / {t['sla_overdue']}" for t in a["trend"][-10:]]
    lines.append("Principales riesgos:")
    lines += [f"- {r['cve_id']} en {r['hostname']} | riesgo {r['risk_score']} | SLA {r['sla_due_date']}" for r in a["top_risks"]]
    lines.append("Activos más expuestos:")
    lines += [f"- {t['hostname']} | criticidad {t['criticality']} | {t['kev_count']} hallazgos KEV" for t in a["top_assets"]]
    return "\n".join(lines)


def _text(s: ExecutiveSummary) -> str:
    return "\n".join([s.tendencia, *[r.texto for r in s.riesgos_principales], *s.recomendaciones])


def executive_summary(db: Session, *, user_id: uuid.UUID | None) -> dict[str, Any]:
    a = stats.aggregates(db)
    allowed = grounding.Allowed()
    for r in a["top_risks"]:
        allowed.add_cves([r["cve_id"]])
        allowed.add_hosts([r["hostname"]])
    for t in a["top_assets"]:
        allowed.add_hosts([t["hostname"]])
    prompt = (PROMPTS / "summary.md").read_text(encoding="utf-8").replace("{contexto}", _context(a))
    sources = {"cves": sorted(allowed.cves), "hosts": sorted(allowed.hosts)}
    with tracked(db, user_id=user_id, feature="exec_summary", prompt=prompt, sources=sources) as tr:
        tr.mark_engine("langchain")
        model = providers.get_chat_model()
        messages: list[Any] = [SystemMessage(system_prompt()), HumanMessage(prompt)]
        out: ExecutiveSummary | None = None
        issues: list[str] = []
        for attempt in range(2):
            try:
                with providers.llm_slot():
                    res = cast(dict[str, Any], providers.call_llm(lambda: model.with_structured_output(ExecutiveSummary, include_raw=True).invoke(messages)))
            except Exception as e:  # noqa: BLE001
                raise providers.AIUnavailable(f"El modelo no respondió: {e.__class__.__name__}") from None
            tr.add_usage(res.get("raw"))
            cand = res.get("parsed")
            if not isinstance(cand, ExecutiveSummary):
                issues = ["estructura inválida"]
            else:
                issues = grounding.problems(_text(cand), allowed)
                for r in cand.riesgos_principales:  # los CVE/activos listados también deben ser reales
                    issues += [f"CVE no respaldado: {c}" for c in r.cve_ids if c.upper() not in allowed.cves]
                    issues += [f"Activo no respaldado: {h}" for h in r.activos if h.lower() not in allowed.hosts]
                if not issues and cand.recomendaciones:
                    out = cand
                    break
            if attempt == 0:
                messages.append(HumanMessage("Tu respuesta tuvo problemas: " + "; ".join(issues) + ". Corrígela usando solo el contexto."))
        if out is None:
            tr.set_output({"issues": issues}, status="ungrounded", error="; ".join(issues)[:500])
            raise Ungrounded(issues)
        result = {"summary": out.model_dump(), "model": providers.info().model, "provider": providers.info().provider,
                  "generated_at": datetime.now(UTC).isoformat(), "interaction_id": str(tr.row.id)}  # fmt: skip
        tr.set_output(result)
    return result
