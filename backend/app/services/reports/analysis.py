"""Reportes analíticos: perfil del inventario (estadística descriptiva + calidad de datos) y evaluación de criterios
frente a KEV. Las cifras salen de services/descriptive.py y services/evaluation.py, las mismas que ve el Resumen."""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import descriptive, evaluation
from app.services.intel import get_active_config
from app.services.reports.model import Chart, Report, ReportError, Table, fmt_date, fmt_num

STATUS = {"ok": "Correcto", "warn": "Aviso", "info": "Información"}


def _n(v: float | None, unit: str = "", digits: int = 1) -> str:
    return fmt_num(v, digits, " %" if unit == "%" else "")


def _lines(items: list[str]) -> str:
    return " ".join(items)


def inventory_profile(db: Session) -> Report:
    d = descriptive.descriptive(db)
    q = d["quality"]
    warns = [c for c in q["checks"] if c["status"] == "warn"]
    kpis = [("Hallazgos abiertos", str(d["n"])), ("En KEV", str(d["kev"]))]
    if d["n"]:
        kpis.append(("Proporción en KEV", f"{fmt_num(100 * d['kev'] / d['n'], 0)} %"))
    kpis.append(("Avisos de calidad", str(len(warns))))

    tables: list[Table] = []
    if q["checks"]:
        tables.append(Table(
            "Calidad de los datos", ["Validación", "Estado", "Detalle"],
            [[c["label"], STATUS[c["status"]], c["detail"]] for c in q["checks"]],
            how_to_read=_lines(q["interpretation"]) + " Un aviso no invalida las cifras, pero indica qué lectura puede estar sesgada.",
        ))  # fmt: skip

    charts: list[Chart] = []
    if d["variables"]:
        rows = []
        for v in d["variables"]:
            s, u = v["summary"], v["unit"]
            rows.append([v["label"] + (" (%)" if u == "%" else ""), s["n"], s["missing"], _n(s["mean"]), _n(s["std"]), _n(s["min"]),
                         _n(s["p25"]), _n(s["median"]), _n(s["p75"]), _n(s["p90"]), _n(s["max"])])  # fmt: skip
            charts.append(Chart(
                f"{v['label']}: distribución por tramos", [b["label"] for b in v["distribution"]],
                [("Hallazgos", [float(b["count"]) for b in v["distribution"]])], kind="bar", x_label="Hallazgos abiertos",
                how_to_read=f"{d['how_to_read']['distribution']} {_lines(v['interpretation'])}",
            ))  # fmt: skip
        tables.append(Table(
            "Resumen estadístico", ["Variable", "Con dato", "Sin dato", "Media", "Desv. est.", "Mín.", "P25", "Mediana", "P75", "P90", "Máx."],
            rows, right=set(range(1, 11)),
            how_to_read=d["how_to_read"]["summary"] + " " + _lines([t for v in d["variables"] for t in v["interpretation"][:2]]),
        ))  # fmt: skip
        for g in d["groups"]:
            tables.append(Table(
                f"Por {g['label'].lower()}", ["Grupo", "Hallazgos", "En KEV", "% KEV", "Mediana score", "Mediana EPSS", "Mediana CVSS", "Lectura"],
                [[r["label"], r["n"], r["kev"], _n(r["kev_pct"], "%", 0), _n(r["median_score"]), _n(r["median_epss"], "%"), _n(r["median_cvss"]),
                  "Orientativo" if r["small"] else ""] for r in g["rows"]],  # fmt: skip
                right={1, 2, 3, 4, 5, 6}, how_to_read=d["how_to_read"]["groups"] + " " + _lines(g["interpretation"]),
            ))  # fmt: skip
        kv = d["kev_vs_rest"]
        if kv:
            tables.append(Table(
                "En KEV frente al resto", ["Grupo", "Hallazgos", "Mediana EPSS", "Mediana CVSS"],
                [["En KEV", kv["kev_n"], _n(kv["kev_median_epss"], "%"), _n(kv["kev_median_cvss"])],
                 ["Resto", kv["rest_n"], _n(kv["rest_median_epss"], "%"), _n(kv["rest_median_cvss"])]],  # fmt: skip
                right={1, 2, 3}, how_to_read=_lines(kv["interpretation"]) or d["how_to_read"]["groups"],
            ))  # fmt: skip
    return Report("inventory_profile", "Perfil del inventario", "Estadística descriptiva de los hallazgos abiertos (score, EPSS y CVSS)",
                  datetime.now(UTC), kpis=kpis, tables=tables, charts=charts, findings=d["interpretation"],
                  notes=[f"{c['label']}: {c['detail']}" for c in warns])  # fmt: skip


def criteria_evaluation(db: Session) -> Report:
    _, params = get_active_config(db)
    e = evaluation.evaluation(db)
    kpis = [("CVE distintos", str(e["n"])), ("En KEV", str(e.get("positives", 0)))]
    if e["n"]:
        kpis.append(("Proporción en KEV", f"{fmt_num(e['prevalence'], 0)} %"))
    preds = sorted(e["predictors"], key=lambda p: -(p["auc"] or 0))
    if preds:
        kpis.append((f"Mejor AUC ({preds[0]['label']})", fmt_num(preds[0]["auc"], 2)))

    tables: list[Table] = []
    charts: list[Chart] = []
    if preds:
        tables.append(Table(
            "Capacidad de separación", ["Criterio", "AUC", "IC 95 %", "Precisión media", "Calidad"],
            [[p["label"], fmt_num(p["auc"], 2), f"{fmt_num(p['auc_ci'][0], 2)} a {fmt_num(p['auc_ci'][1], 2)}" if p["auc_ci"] else "—",
              fmt_num(p["ap"], 2), evaluation._quality_of(p["auc"]) if p["auc"] is not None else "—"] for p in preds],  # fmt: skip
            right={1, 2, 3}, how_to_read=e["how_to_read"]["roc"] + " " + _lines(e["interpretation"][1:3]),
        ))  # fmt: skip
        tables.append(Table(
            "Reglas fijas: matriz de confusión",
            ["Regla", "KEV marcados", "Otros marcados", "KEV sin marcar", "Otros sin marcar", "Cobertura", "Precisión", "Esfuerzo"],
            [[r["label"], r["tp"], r["fp"], r["fn"], r["tn"], _n(r["coverage"], "%", 0), _n(r["efficiency"], "%", 0), _n(r["effort"], "%", 0)]
             for r in e["rules"]],  # fmt: skip
            right=set(range(1, 8)),
            how_to_read=e["how_to_read"]["rules"] + " «KEV sin marcar» es explotación real que la regla dejaría pasar.",
        ))  # fmt: skip
        charts.append(Chart("Curva ROC", [], [], kind="xy", ref="diagonal", x_label="Otros CVE arrastrados", y_label="KEV capturados",
                            xy=[(p["label"], [(pt["fpr"], pt["tpr"]) for pt in p["roc"]]) for p in preds],
                            how_to_read=e["how_to_read"]["roc"]))  # fmt: skip
        charts.append(Chart("Precisión frente a cobertura", [], [], kind="xy", ref=f"h:{e['prevalence'] / 100:.4f}",
                            x_label="Cobertura de KEV", y_label="Precisión",
                            xy=[(p["label"], [(pt["recall"], pt["precision"]) for pt in p["pr"]]) for p in preds],
                            how_to_read=e["how_to_read"]["pr"]))  # fmt: skip
    findings: list[str] = list(e["interpretation"])
    findings.append(f"Criterios evaluados sin KEV; el score completo (piso de KEV {fmt_num(params.kev_floor, 0)}) no se evalúa porque "
                 "incluye KEV y daría un resultado perfecto por construcción.")  # fmt: skip
    _add_universe(db, tables, charts, findings)
    return Report("criteria_evaluation", "Evaluación de criterios frente a KEV",
                  "Qué criterio habría puesto primero los CVE con explotación confirmada (por CVE único)", datetime.now(UTC),
                  kpis=kpis, tables=tables, charts=charts, findings=findings)  # fmt: skip


def _add_universe(db: Session, tables: list[Table], charts: list[Chart], findings: list[str]) -> None:
    """La prueba sobre todo el universo de CVE tiene su propio reporte; aquí solo se remite a él."""
    from app.services import universe

    u = universe.latest(db)
    if u is None or u.get("auc") is None:
        findings.append("Para saber si EPSS anticipa lo que entrará a KEV fuera de este inventario, calcule la prueba sobre todo el "
                        "universo de CVE (Resumen → «Calcular») y exporte el reporte «Prueba prospectiva de EPSS».")  # fmt: skip
    else:
        findings.append(f"Sobre todo el universo de CVE, el EPSS de hace {u['horizon_days']} días anticipó las nuevas entradas a KEV con "
                        f"AUC {fmt_num(u['auc'], 2)}: detalle en el reporte «Prueba prospectiva de EPSS».")  # fmt: skip


def epss_universe(db: Session) -> Report:
    from app.services import universe

    u = universe.latest(db)
    if u is None:
        raise ReportError("Aún no se calculó la prueba sobre el universo de CVE: use «Calcular» en el Resumen")
    when = f"EPSS del {fmt_date(date.fromisoformat(u['as_of']))} · KEV hasta {fmt_date(date.fromisoformat(u['until']))}"
    kpis = [("CVE evaluados", f"{u['n']:,}".replace(",", " ")), (f"Entraron a KEV en {u['horizon_days']} días", str(u["positives"]))]
    tables: list[Table] = []
    charts: list[Chart] = []
    if u.get("auc") is not None:
        kpis.append(("AUC (IC 95 %)", f"{fmt_num(u['auc'], 2)} ({fmt_num(u['auc_ci'][0], 2)} a {fmt_num(u['auc_ci'][1], 2)})"))
        tables.append(Table(
            "Esfuerzo frente a cobertura", ["Parchear el primer", "CVE", "Entradas a KEV cubiertas", "Cobertura", "Veces mejor que el azar"],
            [[_n(e["share_pct"], "%"), f"{e['cves']:,}".replace(",", " "), e["captured"], _n(e["coverage_pct"], "%", 0), fmt_num(e["lift"], 0)]
             for e in u["effort"]],  # fmt: skip
            right={1, 2, 3, 4}, how_to_read=u["how_to_read"]["effort"],
        ))  # fmt: skip
        tables.append(Table(
            "Reglas por umbral de EPSS", ["Regla", "CVE marcados", "Esfuerzo", "Entradas a KEV cubiertas", "Cobertura"],
            [[f"EPSS ≥ {fmt_num(r['threshold_pct'], 0)} %", f"{r['marked']:,}".replace(",", " "), _n(r["effort_pct"], "%", 2), r["captured"],
              _n(r["coverage_pct"], "%", 0)] for r in u["rules"]],  # fmt: skip
            right={1, 2, 3, 4}, how_to_read=u["how_to_read"]["rules"],
        ))  # fmt: skip
        charts.append(Chart(f"Curva ROC (AUC {fmt_num(u['auc'], 2)})", [], [], kind="xy", ref="diagonal",
                            x_label="CVE que no entraron a KEV", y_label="KEV anticipados",
                            xy=[("EPSS", [(p["fpr"], p["tpr"]) for p in u["roc"]])], how_to_read=u["how_to_read"]["curves"]))  # fmt: skip
    model = f" · modelo EPSS {u['model_version']}" if u.get("model_version") else ""
    return Report("epss_universe", "Prueba prospectiva de EPSS", f"Todo el universo de CVE · {when}{model}", datetime.now(UTC),
                  kpis=kpis, tables=tables, charts=charts, findings=u["interpretation"])  # fmt: skip


BUILDERS: dict[str, Any] = {"inventory_profile": inventory_profile, "criteria_evaluation": criteria_evaluation, "epss_universe": epss_universe}

CATALOG: list[dict[str, Any]] = [
    {"key": "inventory_profile", "kind": "analysis", "title": "Perfil del inventario",
     "description": "Estadística descriptiva de score, EPSS y CVSS, por criticidad y entorno, con la validación de los datos.", "period": False},
    {"key": "criteria_evaluation", "kind": "analysis", "title": "Evaluación de criterios frente a KEV",
     "description": "Curvas ROC y precisión-cobertura, AUC con IC 95 % y matrices de confusión de CVSS, EPSS y el score sin KEV.", "period": False},
    {"key": "epss_universe", "kind": "analysis", "title": "Prueba prospectiva de EPSS",
     "description": "Sobre todo el universo de CVE: si el EPSS de hace N días anticipó lo que entró a KEV (último cálculo guardado).", "period": False},
]  # fmt: skip
