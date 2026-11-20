import json
from datetime import timedelta

import pandas as pd

from app.ml import dataset as ds
from app.ml.metrics import evaluate
from app.ml.training import fit_predict

df = ds.load("/data/ml/datasets/8f99a75b-c59f-47ab-80e8-a29de8632114.csv.gz")
dev = df[df.split == "desarrollo"]
rest = df[df.split.isin(["validacion", "prueba"])]
v0 = df[df.split == "validacion"].snapshot.min()
out = {"unique_events": {sp: int(g[g.label == 1].cve.nunique()) for sp, g in df.groupby("split")}}
out["unique_events_total"] = int(df[df.label == 1].cve.nunique())
cfg = {
    "logreg": {"C": 0.001204224194689176, "class_weight": "none"},
    "random_forest": {"max_depth": 10, "class_weight": "none", "max_features": "sqrt", "n_estimators": 153, "min_samples_leaf": 34},
    "hgb": {"max_iter": 200, "class_weight": "balanced", "learning_rate": 0.08, "max_leaf_nodes": 31, "min_samples_leaf": 50, "l2_regularization": 0.01},
}
dev_p = dev[dev.snapshot.map(lambda s: s + timedelta(days=90) <= v0)]
out["dev_snaps"] = {"full": int(dev.snapshot.nunique()), "purged": int(dev_p.snapshot.nunique())}
res = {}
for algo, p in cfg.items():
    r = {}
    for tag, tr in (("sin_embargo", dev), ("con_embargo", dev_p)):
        _, s = fit_predict(algo, p, 7, tr, rest)
        x = rest[["split", "label", "weight"]].copy()
        x["s"] = s
        r[tag] = {sp: {k: v for k, v in evaluate(g.label.to_numpy(), g.s.to_numpy(), g.weight.to_numpy()).items() if k in ("pr_auc", "roc_auc", "recall_1pct", "recall_5pct")} for sp, g in x.groupby("split")}
    res[algo] = r
out["retrain"] = res
print(json.dumps(out, indent=1))
