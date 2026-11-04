"""Enriquecimiento de tickets con IA: el modelo SOLO redacta (resumen, urgencia, pasos); los activos, las
referencias y las fuentes salen directamente de la base de datos. Todo se valida contra lo recuperado."""

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import grounding, langflow, nvd, providers
from app.ai.audit import Tracker, tracked
from app.ai.schemas import AffectedAsset, LLMEnrichment, TicketEnrichment
from app.models.intel import KevEntry
from app.models.inventory import Asset, Vulnerability
from app.models.ops import Ticket, TicketEvent

PROMPTS = Path(__file__).parent / "prompts"
CRITICALITY = {1: "Baja", 2: "Media", 3: "Alta", 4: "Crítica"}
URL_IN_NOTES = grounding.URL_RE


class EnrichmentError(RuntimeError):
    pass


class Ungrounded(EnrichmentError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("; ".join(issues))
        self.issues = issues


@dataclass
class Context:
    text: str
    allowed: grounding.Allowed
    assets: list[AffectedAsset]
    refs: list[str]
    sources: dict[str, Any] = field(default_factory=dict)
    required_action: str = ""  # texto de CISA tal cual; base de los pasos de remediación
    support_text: str = ""  # lo que respalda los pasos: acción requerida y descripciones
    facts: list[str] = field(default_factory=list)  # razones de urgencia deterministas (sin IA)


def system_prompt() -> str:
    return (PROMPTS / "system.md").read_text(encoding="utf-8")


def user_prompt(ctx: Context) -> str:
    return (PROMPTS / "enrichment.md").read_text(encoding="utf-8").replace("{contexto}", ctx.text)


def build_context(db: Session, ticket: Ticket) -> Context:
    vuln: Vulnerability = ticket.vulnerability
    cve = vuln.cve_id
    kev = db.get(KevEntry, cve)
    rows = db.execute(
        select(Vulnerability, Asset).join(Asset, Asset.id == Vulnerability.asset_id)
        .where(Vulnerability.cve_id == cve, Vulnerability.status.in_(("open", "in_progress")))
        .order_by(Asset.criticality.desc(), Asset.hostname)
    ).all()  # fmt: skip
    assets = [AffectedAsset(hostname=a.hostname, criticidad=CRITICALITY[a.criticality], entorno=a.environment) for _, a in rows]
    if ticket.vulnerability.asset.hostname not in {a.hostname for a in assets}:
        a = ticket.vulnerability.asset
        assets.insert(0, AffectedAsset(hostname=a.hostname, criticidad=CRITICALITY[a.criticality], entorno=a.environment))
    nvd_data = nvd.get_cve(db, cve)
    refs: list[str] = []
    if kev:
        refs += [u.rstrip(".,;") for u in URL_IN_NOTES.findall(kev.notes or "")]
    if nvd_data:
        refs += nvd_data["references"]
    refs = list(dict.fromkeys(refs))[:10]

    lines = [f"CVE: {cve}"]
    if kev:
        lines += [
            f"Proveedor / producto: {kev.vendor_project} / {kev.product}",
            "Nombre: " + grounding.untrusted("KEV", kev.vulnerability_name, 300),
            f"Agregado a KEV: {kev.date_added.isoformat()} | Fecha límite de CISA: {kev.due_date.isoformat()}",
            f"Uso conocido en ransomware: {'sí' if kev.ransomware_use == 'Known' else 'no confirmado'}",
            "Descripción: " + grounding.untrusted("KEV", kev.short_description),
            "Acción requerida: " + grounding.untrusted("KEV", kev.required_action),
        ]
    else:
        lines.append("Este CVE NO está en el catálogo KEV.")
    from sqlalchemy import text as sql

    e = db.execute(
        sql("SELECT epss, percentile FROM epss_scores WHERE cve_id = :c ORDER BY score_date DESC LIMIT 1"), {"c": cve}
    ).first()
    lines.append(f"EPSS: {float(e[0]) * 100:.1f} % (percentil {float(e[1]) * 100:.1f})" if e else "EPSS: sin dato")
    if vuln.cvss_score is not None:
        lines.append(f"CVSS: {float(vuln.cvss_score)}")
    if vuln.risk_score is not None:
        lines.append(f"Riesgo calculado: {float(vuln.risk_score):.1f} ({vuln.risk_band})")
    lines.append("Equipos afectados (abiertos con este CVE):")
    lines += [f"- {a.hostname} | criticidad {a.criticidad} | entorno {a.entorno}" for a in assets]
    if nvd_data and nvd_data.get("description"):
        lines.append("Descripción NVD: " + grounding.untrusted("NVD", nvd_data["description"]))
    if refs:
        lines.append("Referencias:")
        lines += [f"- {u}" for u in refs]

    facts: list[str] = []
    if kev:
        facts.append(f"{cve} está en el catálogo KEV de CISA (explotación activa confirmada); fecha límite de CISA: {kev.due_date.strftime('%d/%m/%Y')}.")
        if kev.ransomware_use == "Known":
            facts.append("Hay uso conocido en campañas de ransomware.")
    if e:
        facts.append(f"EPSS de {float(e[0]) * 100:.1f} %: probabilidad de explotación en los próximos 30 días.")
    top = [a for a in assets if a.criticidad in ("Crítica", "Alta")]
    if top:
        facts.append("Equipos de criticidad alta o crítica afectados: " + ", ".join(f"{a.hostname} ({a.criticidad})" for a in top[:5]) + ".")
    allowed = grounding.Allowed(urls=set(refs))
    allowed.add_cves([cve])
    allowed.add_hosts(a.hostname for a in assets)
    sources = {"cve": cve, "kev": kev is not None, "nvd": nvd_data is not None, "hosts": [a.hostname for a in assets],
               "urls": refs}  # fmt: skip
    support = " ".join(
        filter(None, [kev.required_action if kev else "", kev.short_description if kev else "", (nvd_data or {}).get("description", "")])
    )
    return Context(
        "\n".join(lines), allowed, assets, refs, sources, kev.required_action if kev else "", support, facts
    )


_WORD = re.compile(r"[a-záéíóúñü]{5,}")
_FACT_MARKERS = ("kev", "epss", "cisa", "ransomware", "criticidad", "crítica", "fecha límite", "explotación", "explotada")


def refine(o: LLMEnrichment, ctx: Context) -> dict[str, Any]:
    """Un modelo pequeño puede redactar frases plausibles pero sin respaldo. Se conservan solo los pasos que se
    apoyan en la acción requerida de CISA y las descripciones, y solo las razones con un dato concreto; la acción
    de CISA va siempre primero, tal cual, y los hechos deterministas completan la urgencia."""
    support = set(_WORD.findall(ctx.support_text.lower()))

    def uniq(items: list[str]) -> list[str]:
        return list(dict.fromkeys(i.strip() for i in items if i.strip()))

    steps = [x for x in uniq(o.pasos_remediacion) if len(support & set(_WORD.findall(x.lower()))) >= 2][:3]
    if ctx.required_action:
        steps.insert(0, f"Acción requerida por CISA: {ctx.required_action.strip()[:800]}")
    reasons = [
        r for r in uniq(o.por_que_urgente)
        if any(m in r.lower() for m in _FACT_MARKERS) or grounding.CVE_RE.search(r) or any(h in r.lower() for h in ctx.allowed.hosts)
    ]
    for f in ctx.facts:
        if len(reasons) >= 3:
            break
        if f not in reasons:
            reasons.append(f)
    return {"resumen": o.resumen.strip(), "por_que_urgente": reasons[:5], "pasos_remediacion": steps[:4]}


def _all_text(o: LLMEnrichment) -> str:
    return "\n".join([o.resumen, *o.por_que_urgente, *o.pasos_remediacion])


def _via_langchain(ctx: Context, tracker: Tracker, correction: str | None = None) -> LLMEnrichment:
    model = providers.get_chat_model()
    messages: list[Any] = [SystemMessage(system_prompt()), HumanMessage(user_prompt(ctx))]
    if correction:
        messages.append(HumanMessage(correction))
    try:
        with providers.llm_slot():
            result = cast(dict[str, Any], providers.call_llm(lambda: model.with_structured_output(LLMEnrichment, include_raw=True).invoke(messages)))
    except Exception as e:  # noqa: BLE001 - el proveedor puede fallar de muchas formas
        raise providers.AIUnavailable(f"El modelo no respondió: {e.__class__.__name__}") from None
    tracker.add_usage(result.get("raw"))
    parsed = result.get("parsed")
    if not isinstance(parsed, LLMEnrichment):
        raise EnrichmentError("El modelo no devolvió la estructura esperada")
    return parsed


def _clamp(obj: dict[str, Any]) -> dict[str, Any]:
    """El JSON libre de un modelo pequeño puede traer listas largas o repetidas: se deduplica y se recorta."""

    def items(key: str, n: int) -> list[str]:
        vals = obj.get(key)
        return list(dict.fromkeys(str(v)[:320] for v in vals if str(v).strip()))[:n] if isinstance(vals, list) else []

    return {"resumen": str(obj.get("resumen", ""))[:700], "por_que_urgente": items("por_que_urgente", 5),
            "pasos_remediacion": items("pasos_remediacion", 4)}  # fmt: skip


def _via_langflow(ctx: Context, tracker: Tracker) -> LLMEnrichment:
    with providers.llm_slot():
        raw = langflow.run_flow(ctx.text)
    try:
        return LLMEnrichment.model_validate(_clamp(langflow.parse_json_object(raw)))
    except Exception as e:  # noqa: BLE001
        raise langflow.LangflowError(f"El flow devolvió una estructura inválida: {e.__class__.__name__}") from None


def _generate(ctx: Context, tracker: Tracker, engine: str) -> LLMEnrichment:
    """LangFlow primero (si hay), con respaldo en LangChain; un reintento con corrección si no pasa el grounding."""
    out: LLMEnrichment | None = None
    if engine in ("auto", "langflow") and providers.info().provider == "ollama" and langflow.is_configured():
        try:
            out = _via_langflow(ctx, tracker)
            tracker.mark_engine("langflow")
        except langflow.LangflowError:
            if engine == "langflow":
                raise
            out = None  # respaldo: la misma lógica con LangChain
    if out is None:
        out = _via_langchain(ctx, tracker)
        tracker.mark_engine("langchain")
    issues = grounding.problems(_all_text(out), ctx.allowed)
    if issues or not out.por_que_urgente or not out.pasos_remediacion:
        correction = (
            "Tu respuesta anterior mencionó datos que NO están en <contexto>: " + "; ".join(issues or ["listas vacías"])
            + ". Corrígela usando únicamente el contexto."
        )
        out = _via_langchain(ctx, tracker, correction)
        tracker.mark_engine("langchain")
        issues = grounding.problems(_all_text(out), ctx.allowed)
        if issues or not out.por_que_urgente or not out.pasos_remediacion:
            raise Ungrounded(issues or ["la respuesta quedó incompleta"])
    return out


def enrich_ticket(
    db: Session, ticket: Ticket, *, user_id: uuid.UUID | None, actor: str = "user", engine: str = "auto"
) -> TicketEnrichment:
    ctx = build_context(db, ticket)
    with tracked(db, user_id=user_id, feature="enrich", prompt=user_prompt(ctx), sources=ctx.sources, actor=actor) as tr:
        try:
            llm = _generate(ctx, tr, engine)
        except Ungrounded as e:
            tr.set_output({"issues": e.issues}, status="ungrounded", error=str(e)[:500])
            raise
        result = TicketEnrichment(
            **refine(llm, ctx), activos_afectados=ctx.assets, referencias=ctx.refs,
            fuentes=[s for s, ok in (("CISA KEV", ctx.sources["kev"]), ("NVD", ctx.sources["nvd"]), ("Base de datos del radar", True)) if ok],
        )  # fmt: skip
        tr.set_output(result.model_dump())
        ticket.ai_enrichment = result.model_dump()
        ticket.ai_generated = True
        db.add(TicketEvent(ticket_id=ticket.id, user_id=user_id, event="enriched",
                           data={"model": providers.info().model, "engine": tr.row.engine}))  # fmt: skip
    return result
