"""Fase 2: calcula la partición 70/15/15 con embargo y la factibilidad de la CV temporal purgada. Solo stdlib.
Uso: python articulo/protocolo/scripts/f2_layout.py > articulo/protocolo/resultados/f2_layout.json"""
import json
from datetime import date, timedelta

N = 90
UNTIL = date(2026, 11, 18)


def snaps(start: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d + timedelta(days=N) <= UNTIL:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def purge(train: list[date], block_start: date) -> list[date]:
    """Quita de `train` las fotos cuya ventana de etiqueta (S, S+N] llega al bloque siguiente."""
    return [s for s in train if s + timedelta(days=N) <= block_start]


def layout(s: list[date], frac: float = 0.15) -> dict:
    n_t = n_v = round(frac * len(s))
    test = s[-n_t:]
    pre = purge(s[:-n_t], test[0])  # fotos que no cruzan hacia la prueba
    val = pre[-n_v:]
    dev = purge(pre[:-n_v], val[0])
    dropped = [x for x in s if x not in dev + val + test]
    tot = len(dev) + len(val) + len(test)
    return {"n_total": len(s), "dev": [str(dev[0]), str(dev[-1]), len(dev)], "val": [str(val[0]), str(val[-1]), len(val)],
            "test": [str(test[0]), str(test[-1]), len(test)], "embargo_dropped": [str(x) for x in dropped],
            "shares_pct": [round(100 * len(x) / tot, 1) for x in (dev, val, test)]}


def folds(dev: list[date], k: int, v: int, first_val: int | None = None) -> list[dict]:
    """k pliegues expansivos con bloques de v fotos, los últimos del arreglo; train purgado."""
    first = first_val if first_val is not None else len(dev) - k * v
    out = []
    if first < 1:
        return [{"train_n": 0, "val": ["", ""]}]
    for i in range(k):
        a = first + i * v
        va = dev[a : a + v]
        tr = purge(dev[:a], va[0])
        out.append({"train_n": len(tr), "val": [str(va[0]), str(va[-1])]})
    return out


def nested_ok(dev: list[date], k_out: int, v_out: int, k_in: int, v_in: int, min_train_in: int = 3) -> dict:
    res = []
    for f in folds(dev, k_out, v_out):
        if not f["val"][0]:
            res.append(False)
            continue
        vs = date.fromisoformat(f["val"][0])
        tr = purge([x for x in dev if x < vs], vs)
        if len(tr) < k_in * v_in + min_train_in:
            res.append(False)
            continue
        inner = folds(tr, k_in, v_in)
        res.append(all(x["train_n"] >= min_train_in for x in inner))
    return {"k_out": k_out, "v_out": v_out, "k_in": k_in, "v_in": v_in, "dev_snaps": len(dev), "outer_folds_viable": res}


out = {}
for start in (date(2025, 1, 1), date(2024, 1, 1), date(2023, 4, 1)):
    s = snaps(start)
    L = layout(s)
    dev = [date.fromisoformat(L["dev"][0]) + timedelta(days=0)]  # marcador
    dev = [x for x in s if date.fromisoformat(L["dev"][0]) <= x <= date.fromisoformat(L["dev"][1])]
    out[str(start)] = {"layout": L, "cv": [nested_ok(dev, ko, vo, ki, vi) for ko, vo, ki, vi in
                                           ((5, 2, 3, 1), (4, 3, 2, 2), (4, 3, 2, 1), (3, 3, 2, 2), (4, 4, 2, 2), (5, 3, 3, 2))],
                       "flat_purged_cv": {f"k{k}_v{v}": folds(dev, k, v) for k, v in ((4, 3), (5, 3))}}
print(json.dumps(out, indent=1))
