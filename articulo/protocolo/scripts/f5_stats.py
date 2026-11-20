"""Fase 5 · estadística de comparación, calibración, estabilidad, semillas y explicabilidad (sobre los resultados de la Fase 4).
Se corre en el contenedor:
  docker compose run --rm -T -e PYTHONPATH=/srv -v <repo>/backend/app:/srv/app -v <repo>/articulo/protocolo:/proto backend \
      python /proto/scripts/f5_stats.py <id_dataset_embargo> [parte ...]      partes: stats calib seeds explain (por defecto, todas)
Escribe /proto/resultados/f5/<parte>.json. La prueba se usa UNA vez para informar; el modelo se eligió en validación (F4)."""
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from app.ml import assess, explain, inference
from app.ml import dataset as ds
from app.ml.metrics import evaluate
from app.ml.training import fit_predict

DS_ID = sys.argv[1]
PARTS = sys.argv[2:] or ["stats", "calib", "seeds", "explain"]
R4, R5 = Path("/proto/resultados/f4"), Path("/proto/resultados/f5")
R5.mkdir(parents=True, exist_ok=True)
MODELS = {"logreg": "emb_logreg", "random_forest": "emb_random_forest", "hgb": "emb_hgb"}
SELECTED = "logreg"  # elegido en validación (PR-AUC) en la Fase 4
N_BOOT, N_BLOCK = 500, 300


def dump(name: str, obj: Any) -> None:
    (R5 / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"escrito {name}.json", flush=True)


preds = {k: pd.read_csv(R4 / f"{v}.preds.csv.gz") for k, v in MODELS.items()}
ref = preds[SELECTED]
for k, p in preds.items():  # mismas filas en el mismo orden
    assert (p["cve"].to_numpy() == ref["cve"].to_numpy()).all() and (p["label"].to_numpy() == ref["label"].to_numpy()).all(), k
test_m = (ref["split"] == "prueba").to_numpy()
val_m = (ref["split"] == "validacion").to_numpy()
T, V = ref[test_m].reset_index(drop=True), ref[val_m].reset_index(drop=True)
y, w, cve = T["label"].to_numpy(int), T["weight"].to_numpy(float), T["cve"].to_numpy()
yv, wv = V["label"].to_numpy(int), V["weight"].to_numpy(float)
scores_t = {k: p[test_m]["score"].to_numpy(float) for k, p in preds.items()} | {
    "epss": T["baseline_epss"].to_numpy(float), "cvss": T["baseline_cvss"].to_numpy(float)}
scores_v = {k: p[val_m]["score"].to_numpy(float) for k, p in preds.items()} | {
    "epss": V["baseline_epss"].to_numpy(float), "cvss": V["baseline_cvss"].to_numpy(float)}


def recall_mult(s: np.ndarray, cnt: np.ndarray, share: float) -> float:
    order = np.argsort(-s, kind="stable")
    cw = np.cumsum((w * cnt)[order])
    top = order[cw <= share * cw[-1]]
    pos = (y * cnt).sum()
    return float((y[top] * cnt[top]).sum() / pos) if pos else float("nan")


def stats_part() -> None:
    rng = np.random.default_rng(7)
    codes, uniq = pd.factorize(cve)
    k = len(uniq)
    has_pos = np.zeros(k, bool)
    has_pos[codes[y == 1]] = True
    pc, nc = np.flatnonzero(has_pos), np.flatnonzero(~has_pos)
    keys = list(scores_t)
    dist: dict[str, dict[str, list[float]]] = {m: {"pr_auc": [], "roc_auc": [], "recall_1pct": [], "recall_5pct": []} for m in keys}
    for i in range(N_BOOT):
        cnt = np.bincount(rng.choice(pc, len(pc)), minlength=k) + np.bincount(rng.choice(nc, len(nc)), minlength=k)
        cc = cnt[codes]
        ww = w * cc
        for m in keys:
            s = scores_t[m]
            dist[m]["pr_auc"].append(average_precision_score(y, s, sample_weight=ww))
            dist[m]["roc_auc"].append(roc_auc_score(y, s, sample_weight=ww))
            dist[m]["recall_1pct"].append(recall_mult(s, cc, 0.01))
            dist[m]["recall_5pct"].append(recall_mult(s, cc, 0.05))
    point = {m: evaluate(y, scores_t[m], w) | {"lift_1pct": assess.lift_at(y, scores_t[m], w, 0.01), "lift_5pct": assess.lift_at(y, scores_t[m], w, 0.05)} for m in keys}
    abs_ci = {m: {q: {"point": point[m][q], "ci": [round(float(np.quantile(v, 0.025)), 5), round(float(np.quantile(v, 0.975)), 5)]}
                  for q, v in dist[m].items()} for m in keys}

    def diff(a: str, b: str) -> dict[str, Any]:
        out: dict[str, Any] = {"a": a, "b": b}
        for q in ("pr_auc", "roc_auc", "recall_1pct", "recall_5pct"):
            d = np.array(dist[a][q]) - np.array(dist[b][q])
            p = 2 * min(float((d <= 0).mean()), float((d >= 0).mean()))
            out[q] = {"diff": round(float(point[a][q] - point[b][q]), 5), "ci": [round(float(np.quantile(d, 0.025)), 5), round(float(np.quantile(d, 0.975)), 5)],
                      "p": round(min(1.0, max(p, 1 / N_BOOT)), 4)}
        return out

    fam_a = [diff(m, b) for m in MODELS for b in ("epss", "cvss")]
    fam_b = [diff(SELECTED, m) for m in MODELS if m != SELECTED]
    for fam in (fam_a, fam_b):
        for q in ("pr_auc", "roc_auc"):
            for rec, adj in zip(fam, assess.holm([r[q]["p"] for r in fam]), strict=True):
                rec[q]["p_holm"] = adj
    # utilidad práctica pactada (D5): +5 pp de cobertura al 1 % frente a EPSS y PR-AUC ≥ 2× la de EPSS
    useful = {}
    for m in MODELS:
        dr = next(r for r in fam_a if r["a"] == m and r["b"] == "epss")
        rec_gain = dr["recall_1pct"]["diff"]
        useful[m] = {"recall_1pct_gain_pp": round(100 * rec_gain, 1), "pr_auc_ratio_vs_epss": round(point[m]["pr_auc"] / point["epss"]["pr_auc"], 1),
                     "ci_gain_pp": [round(100 * dr["recall_1pct"]["ci"][0], 1), round(100 * dr["recall_1pct"]["ci"][1], 1)],
                     "meets_practical_criterion": bool(rec_gain >= 0.05 and point[m]["pr_auc"] >= 2 * point["epss"]["pr_auc"]),
                     "significant_pr_auc_holm": bool(dr["pr_auc"]["p_holm"] < 0.05 and dr["pr_auc"]["ci"][0] > 0)}
    # bloques de fotos (sensibilidad)
    blk = pd.to_datetime(T["snapshot"]).map(lambda d: d.toordinal() // 60).to_numpy()
    blocks = {m: assess.bootstrap_diff_cluster(y, w, scores_t[m], scores_t["epss"], blk, n=N_BLOCK, stratify=False) for m in MODELS}
    # McNemar en el punto de operación fijado en VALIDACIÓN (filas; un CVE puede contar varias veces: orientativo)
    mc: dict[str, Any] = {}
    for share in (0.01, 0.05):
        flags = {m: scores_t[m] >= assess.threshold_for(scores_v[m], wv, share) for m in keys}
        mc[f"{int(share * 100)}pct"] = {f"{a}_vs_{b}": assess.mcnemar(y, flags[a], flags[b]) for a in MODELS for b in ("epss", "cvss")} | {
            f"{SELECTED}_vs_{m}": assess.mcnemar(y, flags[SELECTED], flags[m]) for m in MODELS if m != SELECTED}
        mc[f"{int(share * 100)}pct"]["events_flagged"] = {m: int(len({c for c, f, lab in zip(cve, flags[m], y, strict=True) if f and lab == 1})) for m in keys}
    # pliegues externos (CV anidada): Friedman y Wilcoxon (con 4 pliegues, solo descriptivos)
    folds = {m: [f["metrics"] for f in json.load(open(R4 / f"{MODELS[m]}.json", encoding="utf-8"))["folds"]] for m in MODELS}
    base_f = [f["baselines"] for f in json.load(open(R4 / f"{MODELS[SELECTED]}.json", encoding="utf-8"))["folds"]]
    cvres: dict[str, Any] = {}
    for q in ("pr_auc", "roc_auc"):
        cols = {m: [f[q] for f in folds[m]] for m in MODELS} | {"epss": [b["epss"][q] for b in base_f]}
        cvres[q] = {"per_fold": cols, "friedman": assess.friedman(cols),
                    "wilcoxon_logreg_vs": {m: assess.wilcoxon_paired(cols[SELECTED], cols[m]) for m in cols if m != SELECTED}}
    dump("stats", {"n_boot": N_BOOT, "events_test": int(len(set(cve[y == 1]))), "clusters": int(k), "absolute_with_ci": abs_ci,
                   "vs_baselines": fam_a, "vs_selected": fam_b, "practical_utility": useful, "block_bootstrap_vs_epss": blocks,
                   "mcnemar": mc, "outer_folds": cvres})


def stability_and_calibration() -> None:
    full = ds.load(f"/data/ml/datasets/{DS_ID}.csv.gz")
    ver = full.groupby("snapshot")["epss_model"].agg(lambda s: s.mode().iat[0]).astype(str).to_dict()
    stab = []
    snaps = pd.to_datetime(T["snapshot"]).dt.date
    for snap in sorted(snaps.unique()):
        m = (snaps == snap).to_numpy()
        row: dict[str, Any] = {"snapshot": str(snap), "epss_version": ver.get(snap), "events": int(len(set(cve[m & (y == 1)])))}
        for key, s in scores_t.items():
            e = evaluate(y[m], s[m], w[m])
            row[key] = {"pr_auc": e["pr_auc"], "roc_auc": e["roc_auc"]}
        stab.append(row)
    cal: dict[str, Any] = {}
    for m, p in preds.items():
        c = inference.compare_calibrators(p)
        full_c = inference.calibrate(p, n_boot=200)
        t = full_c["test"]
        cal[m] = {"comparison": c, "platt_test": {k: v for k, v in t.items() if not isinstance(v, (list, dict))},
                  "base_rate": full_c["base_rate"], "bands": t.get("bands")}
    dump("stability", stab)
    dump("calibration", cal)


def seeds_part() -> None:
    full = ds.load(f"/data/ml/datasets/{DS_ID}.csv.gz")
    dev, rest = full[full["split"] == "desarrollo"], full[full["split"].isin(["validacion", "prueba"])]
    out: dict[str, Any] = {}
    for algo, name in MODELS.items():
        best = json.load(open(R4 / f"{name}.json", encoding="utf-8"))["best_params"]
        runs = []
        for seed in ((1,) if algo == "logreg" else (1, 2, 3, 4, 5)):
            _, s = fit_predict(algo, best, seed, dev, rest, ("epss_version",), 90)
            x = rest[["split", "label", "weight"]].assign(s=s)
            runs.append({sp: {k: v for k, v in evaluate(g.label.to_numpy(), g.s.to_numpy(), g.weight.to_numpy()).items() if k in ("pr_auc", "roc_auc", "recall_1pct", "recall_5pct")}
                         for sp, g in x.groupby("split")})
        out[algo] = {"params": best, "seeds": runs,
                     "summary_test": {k: {"median": float(np.median([r["prueba"][k] for r in runs])), "min": float(min(r["prueba"][k] for r in runs)),
                                          "max": float(max(r["prueba"][k] for r in runs))} for k in ("pr_auc", "roc_auc", "recall_1pct", "recall_5pct")}}
        print(algo, out[algo]["summary_test"]["pr_auc"], flush=True)
    dump("seeds", out)


def explain_part() -> None:
    full = ds.load(f"/data/ml/datasets/{DS_ID}.csv.gz")
    dev, rest = full[full["split"] == "desarrollo"], full[full["split"].isin(["validacion", "prueba"])]
    res: dict[str, Any] = {}
    for algo in (SELECTED, "hgb"):
        best = json.load(open(R4 / f"{MODELS[algo]}.json", encoding="utf-8"))["best_params"]
        model, s = fit_predict(algo, best, 7, dev, rest, ("epss_version",), 90)
        same = float(np.abs(s - preds[algo]["score"].to_numpy(float)).max())
        pr = rest[["snapshot", "cve", "split", "label", "weight"]].assign(score=s)
        r = explain.explain({"pipeline": model, "drop": ["epss_version"]}, full, pr)
        r["refit_max_abs_diff_vs_saved_scores"] = same
        res[algo] = r
        print(algo, "diferencia máxima con las predicciones guardadas:", same, flush=True)
    dump("explain", res)


if "stats" in PARTS:
    stats_part()
if "calib" in PARTS:
    stability_and_calibration()
if "seeds" in PARTS:
    seeds_part()
if "explain" in PARTS:
    explain_part()
