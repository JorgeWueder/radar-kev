"""Fase 4 · controles (solo lectura de datos; sin Optuna). Se corre en el contenedor con:
  docker compose run --rm -v <repo>/backend/app:/srv/app -v <repo>/articulo/protocolo:/proto backend python /proto/scripts/f4_controls.py <id_embargo> <id_sin_embargo>
1) Líneas base (EPSS, CVSS, azar) en validación y prueba con los eventos únicos.
2) Aislar el efecto del embargo del lado del ENTRENAMIENTO: mismo dataset sin embargo (v3b), mismos hiperparámetros de los
   modelos `leak_*`, mismas validación y prueba; solo cambia si el desarrollo incluye o no las fotos cuya ventana cruza hacia validación."""
import json
import sys
from datetime import timedelta

import numpy as np
import pandas as pd

from app.ml import dataset as ds
from app.ml.metrics import evaluate
from app.ml.training import fit_predict

emb_id, leak_id = sys.argv[1], sys.argv[2]
R = "/proto/resultados/f4"
out: dict = {}

# 1) líneas base
p = pd.read_csv(f"{R}/emb_logreg.preds.csv.gz")
base = {}
for sp, g in p.groupby("split"):
    y, w = g["label"].to_numpy(), g["weight"].to_numpy()
    r = {"events": int(g.loc[g.label == 1, "cve"].nunique())}
    for name, s in (("epss", g["baseline_epss"].to_numpy()), ("cvss", g["baseline_cvss"].to_numpy())):
        r[name] = evaluate(y, s, w)
    rng = np.random.default_rng(0)
    r["azar_pr_auc"] = float(np.mean([evaluate(y, rng.random(len(y)), w)["pr_auc"] for _ in range(100)]))
    base[sp] = r
out["baselines"] = base

# 2) control del lado del entrenamiento
df = ds.load(f"/data/ml/datasets/{leak_id}.csv.gz")
dev = df[df["split"] == "desarrollo"]
rest = df[df["split"].isin(["validacion", "prueba"])]
v0 = df.loc[df["split"] == "validacion", "snapshot"].min()
dev_p = dev[dev["snapshot"].map(lambda s: s + timedelta(days=90) <= v0)]
out["dev_snapshots"] = {"leaky": int(dev["snapshot"].nunique()), "purged": int(dev_p["snapshot"].nunique())}
ctl = {}
for algo in ("logreg", "random_forest", "hgb"):
    best = json.load(open(f"{R}/leak_{algo}.json", encoding="utf-8"))["best_params"]
    res = {"params": best, "runs": {"sin_embargo": {}, "con_embargo": {}}}
    for tag, tr, hz in (("sin_embargo", dev, 0), ("con_embargo", dev_p, 90)):
        per_seed = []
        for seed in (1, 2, 3):
            _, s = fit_predict(algo, best, seed, tr, rest, ("epss_version",), hz)
            x = rest[["split", "label", "weight"]].assign(s=s)
            per_seed.append({sp: {k: v for k, v in evaluate(g.label.to_numpy(), g.s.to_numpy(), g.weight.to_numpy()).items()
                                  if k in ("pr_auc", "roc_auc", "recall_1pct", "recall_5pct")} for sp, g in x.groupby("split")})
        res["runs"][tag] = per_seed
    ctl[algo] = res
out["train_side_embargo_control"] = ctl
json.dump(out, open(f"{R}/controls.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ok")
