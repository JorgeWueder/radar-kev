"""Asistente de consulta en lenguaje natural (LangChain + tool calling).

Sin texto-a-SQL: el modelo solo puede llamar herramientas de SOLO LECTURA con parámetros tipados y consultas
predefinidas, y cada herramienta comprueba el permiso RBAC del usuario que pregunta."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.ai import grounding, providers
from app.ai.audit import tracked
from app.ai.enrichment import CRITICALITY, system_prompt
from app.ai.schemas import AssistantAnswer, Citation
from app.api.deps import user_permissions
from app.models.auth import User
from app.models.intel import KevEntry
from app.models.inventory import Asset, Vulnerability
from app.models.ops import Ticket
from app.services import stats
from app.services.intel import get_active_config
from app.services.scoring import sla_state

PROMPTS = Path(__file__).parent / "prompts"
MAX_ROWS = 15
ACTIVE = ("open", "in_progress")
NO_PERMISSION = {"error": "sin permiso: el rol del usuario no puede consultar esta información"}


_CRIT = {"baja": 1, "media": 2, "alta": 3, "crítica": 4, "critica": 4, "critical": 4, "high": 3, "low": 1, "medium": 2}
_ENV = {"prod": "prod", "produccion": "prod", "producción": "prod", "production": "prod", "staging": "staging",
        "preproduccion": "staging", "preproducción": "staging", "dev": "dev", "desarrollo": "dev"}  # fmt: skip
_SLA = {"vencido": "vencido", "vencidos": "vencido", "vencida": "vencido", "overdue": "vencido", "por_vencer": "por_vencer",
        "por vencer": "por_vencer", "en_plazo": "en_plazo", "en plazo": "en_plazo"}  # fmt: skip
_PRIO = {"critical": "critical", "crítica": "critical", "critica": "critical", "crítico": "critical", "high": "high", "alta": "high",
         "alto": "high", "medium": "medium", "media": "medium", "medio": "medium", "low": "low", "baja": "low", "bajo": "low"}  # fmt: skip


def _int(v: Any, default: int, lo: int = 1, hi: int = MAX_ROWS) -> int:
    """Los modelos pequeños mandan null, cadenas o texto en parámetros opcionales: se normalizan, no se rechazan."""
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _crit(v: Any) -> int | None:
    if isinstance(v, str) and v.strip().lower() in _CRIT:
        return _CRIT[v.strip().lower()]
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 4 else None


def _pick(table: dict[str, str], v: Any) -> str | None:
    return table.get(str(v).strip().lower()) if v is not None else None


def _bool(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ("true", "sí", "si", "1", "yes")


def _text(v: Any) -> str | None:
    t = str(v).strip() if v is not None else ""
    return t or None


class Toolbox:
    """Herramientas del asistente ligadas a (sesión, usuario). Registra lo recuperado para el grounding."""

    def __init__(self, db: Session, user: User) -> None:
        self.db, self.user = db, user
        self.perms = user_permissions(user)
        self.allowed = grounding.Allowed()
        self.calls: list[dict[str, Any]] = []
        _, self.params = get_active_config(db)
        self.today = datetime.now(UTC).date()

    # -- utilidades
    def _ok(self, *codes: str) -> bool:
        return all(c in self.perms for c in codes)

    def _ret(self, name: str, args: dict[str, Any], rows: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> str:
        for r in rows:
            for key in ("cve_id",):
                if r.get(key):
                    self.allowed.add_cves([r[key]])
            if r.get("hostname"):
                self.allowed.add_hosts([r["hostname"]])
            for h in r.get("equipos", []) or []:
                self.allowed.add_hosts([h])
        data = {"total": len(rows), "datos": rows[:MAX_ROWS], **(extra or {})}
        self.calls.append({"tool": name, "args": args, "total": len(rows)})
        return json.dumps(data, ensure_ascii=False, default=str)

    def _denied(self, name: str, args: dict[str, Any]) -> str:
        self.calls.append({"tool": name, "args": args, "denied": True})
        return json.dumps(NO_PERMISSION, ensure_ascii=False)

    def _row(self, v: Vulnerability, kev: KevEntry | None) -> dict[str, Any]:
        a = v.asset
        return {
            "cve_id": v.cve_id, "hostname": a.hostname, "criticidad_activo": CRITICALITY[a.criticality],
            "entorno": a.environment, "riesgo": float(v.risk_score) if v.risk_score is not None else None,
            "banda": v.risk_band, "estado": v.status, "sla_fecha": v.sla_due_date.isoformat() if v.sla_due_date else None,
            "sla_estado": sla_state(self.params, v.sla_due_date, self.today, v.status in ACTIVE),
            "en_kev": kev is not None, "ransomware": bool(kev and kev.ransomware_use == "Known"),
        }  # fmt: skip

    # -- herramientas
    def listar_exposiciones_kev(
        self, criticidad_minima: Any = None, entorno: Any = None, estado_sla: Any = None, limite: Any = 10,
    ) -> str:  # fmt: skip
        """Lista los hallazgos abiertos cuyo CVE está en el catálogo KEV de CISA (explotación activa confirmada).
        Parámetros opcionales: criticidad_minima = criticidad mínima del activo (1 baja, 2 media, 3 alta, 4 crítica);
        entorno = prod, staging o dev; estado_sla = vencido, por_vencer o en_plazo; limite = número de filas (máx. 15)."""
        criticidad_minima, entorno, estado_sla = _crit(criticidad_minima), _pick(_ENV, entorno), _pick(_SLA, estado_sla)
        limite = _int(limite, 10)
        args = {"criticidad_minima": criticidad_minima, "entorno": entorno, "estado_sla": estado_sla, "limite": limite}
        if not self._ok("vulnerabilities:view"):
            return self._denied("listar_exposiciones_kev", args)
        stmt = (
            select(Vulnerability, KevEntry).join(KevEntry, KevEntry.cve_id == Vulnerability.cve_id)
            .join(Asset, Asset.id == Vulnerability.asset_id).where(Vulnerability.status.in_(ACTIVE))
            .order_by(Vulnerability.risk_score.desc().nulls_last())
        )  # fmt: skip
        if criticidad_minima:
            stmt = stmt.where(Asset.criticality >= max(1, min(4, criticidad_minima)))
        if entorno:
            stmt = stmt.where(Asset.environment == entorno)
        rows = [self._row(v, k) for v, k in self.db.execute(stmt).unique().all()]
        if estado_sla:
            rows = [r for r in rows if r["sla_estado"] == estado_sla]
        return self._ret("listar_exposiciones_kev", args, rows[:limite], {"total_real": len(rows)})

    def detalle_cve(self, cve_id: str) -> str:
        """Ficha de un CVE: datos de KEV (acción requerida, fecha límite), EPSS y equipos afectados."""
        cve = cve_id.strip().upper()
        if not self._ok("vulnerabilities:view"):
            return self._denied("detalle_cve", {"cve_id": cve})
        kev = self.db.get(KevEntry, cve)
        vulns = self.db.execute(select(Vulnerability).where(Vulnerability.cve_id == cve)).scalars().unique().all()
        epss = self.db.execute(
            text("SELECT epss, percentile FROM epss_scores WHERE cve_id=:c ORDER BY score_date DESC LIMIT 1"),
            {"c": cve},
        ).first()
        rows = [self._row(v, kev) for v in vulns]
        extra: dict[str, Any] = {"cve": cve, "en_kev": kev is not None, "epss": float(epss[0]) if epss else None,
                                 "percentil": float(epss[1]) if epss else None}  # fmt: skip
        if kev:
            extra.update({"nombre": grounding.untrusted("KEV", kev.vulnerability_name, 300), "fecha_limite_cisa": kev.due_date.isoformat(),
                          "accion_requerida": grounding.untrusted("KEV", kev.required_action, 600)})  # fmt: skip
        if not rows and not kev:
            self.calls.append({"tool": "detalle_cve", "args": {"cve_id": cve}, "total": 0})
            return json.dumps({"total": 0, "datos": [], "mensaje": "El CVE no está en el inventario ni en KEV"}, ensure_ascii=False)
        if kev:
            self.allowed.add_cves([cve])
        return self._ret("detalle_cve", {"cve_id": cve}, rows, extra)

    def activos_mas_expuestos(self, n: Any = 5) -> str:
        """Los activos con más hallazgos abiertos en KEV, con su criticidad. Parámetro n = cuántos activos (máx. 15)."""
        n = _int(n, 5)
        args = {"n": n}
        if not self._ok("vulnerabilities:view"):
            return self._denied("activos_mas_expuestos", args)
        q = self.db.execute(
            select(Asset.hostname, Asset.criticality, Asset.environment, func.count(), func.max(Vulnerability.risk_score))
            .join(Vulnerability, Vulnerability.asset_id == Asset.id)
            .where(Vulnerability.status.in_(ACTIVE), Vulnerability.cve_id.in_(select(KevEntry.cve_id)))
            .group_by(Asset.id).order_by(func.count().desc(), func.max(Vulnerability.risk_score).desc().nulls_last())
            .limit(max(1, min(n, MAX_ROWS)))
        ).all()  # fmt: skip
        rows = [{"hostname": h, "criticidad_activo": CRITICALITY[c], "entorno": e, "hallazgos_kev": int(k),
                 "riesgo_maximo": float(r) if r is not None else None} for h, c, e, k, r in q]  # fmt: skip
        return self._ret("activos_mas_expuestos", args, rows)

    def vulnerabilidades_de_activo(self, hostname: str) -> str:
        """Todos los hallazgos (abiertos o no) de un equipo, por su hostname exacto."""
        host = hostname.strip().lower()
        if not self._ok("vulnerabilities:view"):
            return self._denied("vulnerabilidades_de_activo", {"hostname": host})
        vulns = self.db.execute(
            select(Vulnerability).join(Asset, Asset.id == Vulnerability.asset_id).where(func.lower(Asset.hostname) == host)
            .order_by(Vulnerability.risk_score.desc().nulls_last())
        ).scalars().unique().all()  # fmt: skip
        kev = {k.cve_id: k for k in self.db.execute(select(KevEntry).where(KevEntry.cve_id.in_([v.cve_id for v in vulns]))).scalars()} if vulns else {}
        return self._ret("vulnerabilidades_de_activo", {"hostname": host}, [self._row(v, kev.get(v.cve_id)) for v in vulns])

    def kpis_dashboard(self) -> str:
        """Indicadores generales: CVEs KEV presentes, nuevos en 24 h y 7 días, SLA vencidos y por vencer, MTTR."""
        if not self._ok("dashboard:view"):
            return self._denied("kpis_dashboard", {})
        a = stats.aggregates(self.db)
        keep = ("open_kev", "new_kev_24h", "new_kev_7d", "sla_overdue", "sla_due_soon", "sla_overdue_kev", "active_total",
                "by_band", "mttr_days", "sla_compliance_pct", "resolved_90d")  # fmt: skip
        data = {k: a[k] for k in keep}
        for r in a["top_risks"]:
            self.allowed.add_cves([r["cve_id"]])
            self.allowed.add_hosts([r["hostname"]])
        self.calls.append({"tool": "kpis_dashboard", "args": {}, "total": 1})
        return json.dumps({"total": 1, "datos": [data], "top_riesgos": a["top_risks"]}, ensure_ascii=False, default=str)

    def buscar_catalogo_kev(self, proveedor: Any = None, producto: Any = None, solo_ransomware: Any = False,
                            limite: Any = 10) -> str:  # fmt: skip
        """Busca en el catálogo KEV por proveedor o producto (texto); solo_ransomware = true para limitar a los de uso
        conocido en ransomware; indica qué equipos del inventario están afectados."""
        proveedor, producto, solo_ransomware, limite = _text(proveedor), _text(producto), _bool(solo_ransomware), _int(limite, 10)
        args = {"proveedor": proveedor, "producto": producto, "solo_ransomware": solo_ransomware, "limite": limite}
        if not self._ok("kev:view"):
            return self._denied("buscar_catalogo_kev", args)
        stmt = select(KevEntry).order_by(KevEntry.date_added.desc())
        if proveedor:
            stmt = stmt.where(KevEntry.vendor_project.ilike(f"%{proveedor[:60]}%"))
        if producto:
            stmt = stmt.where(KevEntry.product.ilike(f"%{producto[:60]}%"))
        if solo_ransomware:
            stmt = stmt.where(KevEntry.ransomware_use == "Known")
        found = self.db.execute(stmt.limit(limite)).scalars().all()
        rows = []
        for k in found:
            hosts = list(self.db.execute(
                select(Asset.hostname).join(Vulnerability, Vulnerability.asset_id == Asset.id)
                .where(Vulnerability.cve_id == k.cve_id, Vulnerability.status.in_(ACTIVE))
            ).scalars())  # fmt: skip
            rows.append({"cve_id": k.cve_id, "proveedor": k.vendor_project, "producto": k.product,
                         "nombre": grounding.untrusted("KEV", k.vulnerability_name, 200), "agregado": k.date_added.isoformat(),
                         "fecha_limite_cisa": k.due_date.isoformat(), "ransomware": k.ransomware_use == "Known",
                         "equipos": hosts})  # fmt: skip
        return self._ret("buscar_catalogo_kev", args, rows)

    def tickets_abiertos(self, prioridad: Any = None, estado_sla: Any = None, limite: Any = 10) -> str:
        """Tickets de remediación activos (abiertos o en remediación), con responsable y SLA. Parámetros opcionales:
        prioridad = critica, alta, media o baja; estado_sla = vencido, por_vencer o en_plazo; limite = filas (máx. 15)."""
        prioridad, estado_sla, limite = _pick(_PRIO, prioridad), _pick(_SLA, estado_sla), _int(limite, 10)
        args = {"prioridad": prioridad, "estado_sla": estado_sla, "limite": limite}
        if not self._ok("tickets:view"):
            return self._denied("tickets_abiertos", args)
        stmt = select(Ticket).where(Ticket.status.in_(ACTIVE)).order_by(Ticket.due_date.asc().nulls_last())
        if prioridad:
            stmt = stmt.where(Ticket.priority == prioridad)
        rows = []
        for t in self.db.execute(stmt).scalars().unique():
            state = sla_state(self.params, t.due_date, self.today, True)
            if estado_sla and state != estado_sla:
                continue
            rows.append({"codigo": t.code, "cve_id": t.vulnerability.cve_id, "hostname": t.vulnerability.asset.hostname,
                         "prioridad": t.priority, "estado": t.status, "responsable": t.assignee.full_name if t.assignee else None,
                         "sla_fecha": t.due_date.isoformat() if t.due_date else None, "sla_estado": state})  # fmt: skip
        return self._ret("tickets_abiertos", args, rows[:limite], {"total_real": len(rows)})

    def tools(self) -> list[StructuredTool]:
        fns = (self.listar_exposiciones_kev, self.detalle_cve, self.activos_mas_expuestos, self.vulnerabilidades_de_activo,
               self.kpis_dashboard, self.buscar_catalogo_kev, self.tickets_abiertos)  # fmt: skip
        return [
            StructuredTool.from_function(f, name=f.__name__, description=(f.__doc__ or "").strip(),
                                         handle_tool_error=True, handle_validation_error=True)
            for f in fns
        ]


def ask(db: Session, user: User, question: str, history: list[dict[str, str]] | None = None) -> AssistantAnswer:
    box = Toolbox(db, user)
    system = system_prompt() + "\n" + (PROMPTS / "assistant.md").read_text(encoding="utf-8")
    msgs: list[Any] = []
    for h in (history or [])[-6:]:
        msgs.append(HumanMessage(h["content"]) if h.get("role") == "user" else AIMessage(h["content"]))
    msgs.append(HumanMessage(question))
    with tracked(db, user_id=user.id, feature="assistant", prompt=question, sources={}) as tr:
        agent = create_agent(providers.get_chat_model(), box.tools(), system_prompt=system)
        try:
            with providers.llm_slot():
                result = providers.call_llm(lambda: agent.invoke({"messages": msgs}, config={"recursion_limit": 12}))
        except providers.AIUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise providers.AIUnavailable(f"El modelo no respondió: {e.__class__.__name__}") from None
        messages = result["messages"]
        for m in messages:
            if isinstance(m, AIMessage):
                tr.add_usage(m)
        tool_results = [m for m in messages if isinstance(m, ToolMessage)]
        final = next((str(m.content) for m in reversed(messages) if isinstance(m, AIMessage) and m.content), "")
        # Un host/CVE mencionado por el usuario en su pregunta también se considera respaldado.
        issues = grounding.problems(final, box.allowed)
        answered = [c for c in box.calls if not c.get("denied")]
        empty = not answered or all(c.get("total", 0) == 0 for c in answered)
        if issues:
            answer = AssistantAnswer(
                respuesta="No puedo confirmar esta respuesta porque menciona datos que no provienen de las consultas. "
                          "Reformule la pregunta o consulte las pantallas del radar.",
                sin_datos=empty, advertencias=issues,
            )  # fmt: skip
            tr.set_output(answer.model_dump(), status="ungrounded", error="; ".join(issues)[:500])
        else:
            cites = [Citation(cve_id=c) for c in sorted(set(grounding.CVE_RE.findall(final.upper())))]
            low = final.lower()  # se citan los equipos recuperados que la respuesta menciona (cualquier formato de nombre)
            cites += [Citation(hostname=h) for h in sorted(box.allowed.hosts) if re.search(rf"(?<![\w-]){re.escape(h)}(?![\w-])", low)]
            answer = AssistantAnswer(respuesta=final.strip() or "No hay datos suficientes", citas=cites,
                                     sin_datos=empty or "no hay datos suficientes" in final.lower())  # fmt: skip
            tr.set_output(answer.model_dump())
        tr.row.sources = {"tools": box.calls, "cves": sorted(box.allowed.cves), "hosts": sorted(box.allowed.hosts),
                          "tool_messages": len(tool_results)}  # fmt: skip
    return answer
