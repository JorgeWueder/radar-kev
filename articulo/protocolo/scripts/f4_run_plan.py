"""Fase 4 · plan reducido: genera las configuraciones y corre los experimentos en serie dentro del contenedor.

Uso (desde la raíz del repo), tras construir los datasets:
    python articulo/protocolo/scripts/f4_run_plan.py <id_dataset_embargo> <id_dataset_sin_embargo> [nombre_experimento ...]
Cada experimento escribe resultados/f4/<nombre>.json y .preds.csv.gz (ver app/ml/experiment.py). Si ya existe el JSON, se omite
(reanudable). No reiniciar el backend mientras corre."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "articulo" / "protocolo" / "resultados" / "f4"
N_TRIALS, SEED = 10, 7


def plan(emb: str, leak: str) -> dict[str, dict]:
    base = {"n_trials": N_TRIALS, "seed": SEED, "sampler": "tpe", "k_out": 4, "k_in": 2, "v_out": 3, "v_in": 2}
    p: dict[str, dict] = {}
    for algo in ("logreg", "random_forest", "hgb"):
        p[f"emb_{algo}"] = base | {"algorithm": algo, "dataset": emb, "horizon": 90, "drop": ["epss_version"]}
    for algo in ("logreg", "random_forest", "hgb"):  # control: misma geometría de CV, sin embargo en partición ni pliegues
        p[f"leak_{algo}"] = base | {"algorithm": algo, "dataset": leak, "horizon": 0, "drop": ["epss_version"]}
    p["emb_hgb_con_version"] = base | {"algorithm": "hgb", "dataset": emb, "horizon": 90, "drop": []}
    p["emb_hgb_sin_epss"] = base | {"algorithm": "hgb", "dataset": emb, "horizon": 90, "drop": ["epss_version", "epss"]}
    p["emb_hgb_sin_cvss"] = base | {"algorithm": "hgb", "dataset": emb, "horizon": 90, "drop": ["epss_version", "cvss"]}
    p["emb_logreg_tpe5"] = base | {"algorithm": "logreg", "dataset": emb, "horizon": 90, "drop": ["epss_version"]}  # TPE con 5 pruebas iniciales (tras corregir n_startup_trials)
    p["emb_hgb_tpe5"] = base | {"algorithm": "hgb", "dataset": emb, "horizon": 90, "drop": ["epss_version"]}
    p["emb_logreg_aleatorio"] = base | {"algorithm": "logreg", "dataset": emb, "horizon": 90, "drop": ["epss_version"], "sampler": "random"}
    return p


def main(argv: list[str]) -> int:
    emb, leak, only = argv[1], argv[2], argv[3:]
    OUT.mkdir(parents=True, exist_ok=True)
    cfg_dir = OUT / "configs"
    cfg_dir.mkdir(exist_ok=True)
    for name, c in plan(emb, leak).items():
        if only and name not in only:
            continue
        if (OUT / f"{name}.json").exists():
            print(f"= {name}: ya existe, se omite", flush=True)
            continue
        cfg = {k: v for k, v in c.items() if k != "dataset"} | {
            "name": name, "dataset_path": f"/data/ml/datasets/{c['dataset']}.csv.gz", "out_dir": "/out"}
        (cfg_dir / f"{name}.config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        print(f"> {name}", flush=True)
        cmd = ["docker", "compose", "run", "--rm", "-T", "-v", f"{ROOT / 'backend' / 'app'}:/srv/app",
               "-v", f"{OUT}:/out", "backend", "python", "-m", "app.ml.experiment", f"/out/configs/{name}.config.json"]  # fmt: skip
        r = subprocess.run(cmd, cwd=ROOT, env={**__import__("os").environ, "MSYS_NO_PATHCONV": "1"}, capture_output=True, text=True)
        (OUT / f"{name}.log").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
        print(f"  {'ok' if r.returncode == 0 else 'FALLÓ'} ({name})", flush=True)
        if r.returncode != 0:
            print(r.stderr[-800:], flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
