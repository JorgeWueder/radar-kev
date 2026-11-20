"""Fase 5 · McNemar a nivel de EVENTO (un CVE positivo cuenta una vez; «detectado» = alguna de sus filas de prueba queda sobre el umbral
fijado en validación). Mismo entorno que f5_stats.py. Escribe /proto/resultados/f5/mcnemar_events.json"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from app.ml import assess

R4, R5 = Path("/proto/resultados/f4"), Path("/proto/resultados/f5")
M = {"logreg": "emb_logreg", "random_forest": "emb_random_forest", "hgb": "emb_hgb"}
P = {k: pd.read_csv(R4 / f"{v}.preds.csv.gz") for k, v in M.items()}
ref = P["logreg"]
V, T = ref[ref.split == "validacion"], ref[ref.split == "prueba"]
sv = {k: p[p.split == "validacion"]["score"].to_numpy() for k, p in P.items()} | {"epss": V["baseline_epss"].to_numpy(), "cvss": V["baseline_cvss"].to_numpy()}
st = {k: p[p.split == "prueba"]["score"].to_numpy() for k, p in P.items()} | {"epss": T["baseline_epss"].to_numpy(), "cvss": T["baseline_cvss"].to_numpy()}
wv = V["weight"].to_numpy()
out: dict = {}
for share in (0.01, 0.05):
    det: dict[str, set] = {}
    for k in st:
        flag = st[k] >= assess.threshold_for(sv[k], wv, share)
        det[k] = set(T["cve"].to_numpy()[flag & (T["label"].to_numpy() == 1)])
    events = set(T["cve"].to_numpy()[T["label"].to_numpy() == 1])
    res = {"events": len(events), "detected": {k: len(v) for k, v in det.items()}, "pairs": {}}
    for a in M:
        for b in [x for x in st if x != a]:
            only_a, only_b = len(det[a] - det[b]), len(det[b] - det[a])
            p = float(stats.binomtest(only_a, only_a + only_b, 0.5).pvalue) if only_a + only_b else 1.0
            res["pairs"][f"{a}_vs_{b}"] = {"only_a": only_a, "only_b": only_b, "p": round(p, 4)}
    out[f"{int(share * 100)}pct"] = res
(R5 / "mcnemar_events.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for sh, r in out.items():
    print(sh, r["events"], r["detected"])
    for k, v in r["pairs"].items():
        if k.split("_vs_")[0] == "logreg" or k.endswith("_vs_epss"):
            print("  ", k, v)
