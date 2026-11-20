"""Auditoría Fase 1 del Laboratorio (solo lectura). Uso (desde la raíz del repo):
docker compose cp articulo/protocolo/scripts/audit_f1a.py backend:/tmp/audit_f1a.py
docker compose exec -T -e PYTHONPATH=/srv backend python /tmp/audit_f1a.py > articulo/protocolo/resultados/f1_auditoria.json"""
import json
from datetime import timedelta

import numpy as np
import pandas as pd

from app.ml import dataset as ds
from app.ml.metrics import evaluate
from app.ml.training import forward_folds

DS = "/data/ml/datasets/8f99a75b-c59f-47ab-80e8-a29de8632114.csv.gz"
MODELS = {
    "hgb": "a2bf4010-f70f-46cd-ad2d-30b9def200bb", "logreg": "b0f6bbf6-405d-43ed-be88-32c57b27a205",
    "rf": "7690741a-b270-467e-8fb0-d4719a876b32", "hgb_sin_epss": "78ad0ac6-048f-4dd1-a234-94c65cd8b25b",
    "hgb_sin_cvss": "f0eac190-dc08-42b2-8b2f-d1621ff10573", "logreg_espacio": "f924f3a3-431f-48ec-a95d-deb753842f95",
}
H = 90
out: dict = {}
df = ds.load(DS)

g = df.groupby("snapshot")
per = g.agg(split=("split", "first"), rows=("cve", "size"), pos=("label", "sum"), neg=("label", lambda s: int((s == 0).sum())),
            unique_cve=("cve", "nunique"), neg_w=("weight", "max")).reset_index()
per["prev_real_pct"] = [100 * p / (p + n * w) for p, n, w in zip(per.pos, per.neg, per.neg_w)]
per["label_window_end"] = per["snapshot"].map(lambda s: s + timedelta(days=H))
out["per_snapshot"] = json.loads(per.assign(snapshot=per.snapshot.astype(str), label_window_end=per.label_window_end.astype(str)).to_json(orient="records"))
out["weights"] = {"neg_weight_unique": sorted(df.loc[df.label == 0, "weight"].round(6).unique().tolist())[:5], "pos_weight": sorted(df.loc[df.label == 1, "weight"].unique().tolist())}
out["epss_model_by_snapshot"] = df.groupby("snapshot")["epss_model"].agg(lambda s: s.mode().iat[0]).astype(str).rename(index=str).to_dict()

out["split_ranges"] = df.groupby("split")["snapshot"].agg(["min", "max"]).astype(str).to_dict("index")
v0 = df.loc[df.split == "validacion", "snapshot"].min()
t0 = df.loc[df.split == "prueba", "snapshot"].min()
dev, val, tst = (df[df.split == s] for s in ("desarrollo", "validacion", "prueba"))
pos = df[df.label == 1]
ov = {}
ov["dev_pos_total"] = int(len(dev[dev.label == 1]))
ov["dev_pos_event_after_val_start"] = int((dev[dev.label == 1]["kev_date"] > v0).sum())
ov["val_pos_total"] = int(len(val[val.label == 1]))
ov["val_pos_event_after_test_start"] = int((val[val.label == 1]["kev_date"] > t0).sum())
ov["dev_snaps_with_window_past_val_start"] = [str(s) for s in sorted(dev.snapshot.unique()) if s + timedelta(days=H) > v0]
ov["val_snaps_with_window_past_test_start"] = [str(s) for s in sorted(val.snapshot.unique()) if s + timedelta(days=H) > t0]
cs = {k: set(x[x.label == 1].cve) for k, x in (("dev", dev), ("val", val), ("test", tst))}
ov["same_cve_positive_dev_and_val"] = len(cs["dev"] & cs["val"])
ov["same_cve_positive_val_and_test"] = len(cs["val"] & cs["test"])
ov["same_cve_positive_dev_and_test"] = len(cs["dev"] & cs["test"])
rep = df.groupby("cve")["snapshot"].nunique()
ov["cve_rows_mean_snapshots"] = float(rep.mean())
pr = pos.groupby("cve")["snapshot"].nunique()
ov["positive_cve_unique"] = int(len(pr))
ov["positive_rows"] = int(len(pos))
ov["positive_cve_in_k_snapshots"] = {int(k): int(v) for k, v in pr.value_counts().sort_index().items()}
out["overlap"] = ov

folds = forward_folds(sorted(dev.snapshot.unique()), 5)


def purge_count(snaps_tr, vstart):
    return sum(1 for s in snaps_tr if s + timedelta(days=H) > vstart)


fo = []
for i, (tr, va) in enumerate(folds, 1):
    vstart = min(va)
    trd, vad = dev[dev.snapshot.isin(tr)], dev[dev.snapshot.isin(va)]
    fo.append({"fold": i, "train": [str(min(tr)), str(max(tr))], "val": [str(min(va)), str(max(va))], "n_train_snaps": len(tr),
               "train_snaps_with_window_past_val_start": purge_count(tr, vstart), "val_pos": int(vad.label.sum()),
               "train_pos": int(trd.label.sum()), "train_pos_event_after_val_start": int((trd[trd.label == 1].kev_date > vstart).sum())})
out["outer_folds"] = fo
out["embargo_cost"] = {"dev_to_val_snaps_lost": purge_count(sorted(dev.snapshot.unique()), v0),
                       "val_to_test_snaps_lost": purge_count(sorted(val.snapshot.unique()), t0),
                       "outer_folds_lost": [purge_count(tr, min(va)) for tr, va in folds]}
inner = forward_folds(sorted(dev.snapshot.unique()), 3)
out["inner_final_search_folds"] = [{"train_n": len(tr), "val": [str(min(va)), str(max(va))], "leaky_train_snaps": purge_count(tr, min(va))} for tr, va in inner]
out["epss_scale"] = (df.groupby("epss_model").agg(first=("snapshot", "min"), last=("snapshot", "max"), rows=("cve", "size"),
                     epss_p99=("epss", lambda s: float(s.quantile(0.99)))).astype({"first": str, "last": str}).reset_index().to_dict("records"))

rep_m = {}
for k, mid in MODELS.items():
    p = pd.read_csv(f"/data/ml/models/{mid}.preds.csv.gz")
    r = {sp: evaluate(x.label.to_numpy(), x.score.to_numpy(), x.weight.to_numpy()) for sp, x in p.groupby("split")}
    rep_m[k] = r
    if k == "hgb":
        for b in ("epss", "cvss"):
            for sp, x in p.groupby("split"):
                r[f"base_{b}_{sp}"] = evaluate(x.label.to_numpy(), x[f"baseline_{b}"].to_numpy(), x.weight.to_numpy())
        rng = np.random.default_rng(0)
        for sp, x in p.groupby("split"):
            vals = [evaluate(x.label.to_numpy(), rng.random(len(x)), x.weight.to_numpy())["pr_auc"] for _ in range(20)]
            r[f"azar_{sp}"] = {"pr_auc_mean": float(np.mean(vals)), "prevalence_pct": r[sp]["prevalence_pct"]}
out["reproduced"] = rep_m
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
