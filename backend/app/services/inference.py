"""Pruebas estadísticas robustas para comparar periodos (sin SciPy: solo `math`).

- MTTR (días hasta mitigar): Mann-Whitney U, no paramétrica (los tiempos de remediación son asimétricos), con
  aproximación normal y corrección por empates, más el tamaño del efecto (r de rango biserial).
- Cumplimiento de SLA: prueba z de dos proporciones, más intervalo de Wilson al 95 % de cada periodo.
- Tendencia de una serie diaria: Mann-Kendall con pendiente de Theil-Sen.

Cada resultado trae `interpretation` en español llano. Con muestras pequeñas se dice explícitamente que la conclusión
es débil: nunca se declara una diferencia que los datos no sostienen.
"""

import math
from collections.abc import Sequence
from typing import Any

ALPHA = 0.05
MIN_N = 8  # por debajo, la aproximación normal es poco fiable


def _p(p: float) -> str:
    return "p < 0,001" if p < 0.001 else f"p = {p:.3f}".replace(".", ",")


def _c(x: float, spec: str = ".1f") -> str:
    """Número con coma decimal (la interfaz y los reportes están en español)."""
    return format(x, spec).replace(".", ",")


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def _two_sided(z: float) -> float:
    return min(1.0, 2 * _norm_sf(abs(z)))


def _ranks(values: Sequence[float]) -> tuple[list[float], list[int]]:
    """Rangos promedio y tamaños de los grupos de empates."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    ties: list[int] = []
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        ties.append(j - i + 1)
        i = j + 1
    return ranks, ties


def _median(xs: Sequence[float]) -> float:
    ys = sorted(xs)
    mid = len(ys) // 2
    return ys[mid] if len(ys) % 2 else (ys[mid - 1] + ys[mid]) / 2


def _verdict(p: float | None, small: bool) -> str:
    if p is None:
        return "sin_datos"
    if p < ALPHA:
        return "diferencia_debil" if small else "diferencia"
    return "sin_diferencia"


def mann_whitney(a: Sequence[float], b: Sequence[float]) -> dict[str, Any]:
    """Compara la ubicación de dos muestras independientes (a = periodo anterior, b = periodo actual)."""
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return {"test": "Mann-Whitney U", "n_prev": n1, "n_cur": n2, "p_value": None, "effect": None,
                "verdict": "sin_datos", "interpretation": "Falta un periodo con hallazgos mitigados: no se puede comparar."}  # fmt: skip
    ranks, ties = _ranks([*a, *b])
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    tie_term = sum(t**3 - t for t in ties) / (n * (n - 1)) if n > 1 else 0.0
    var = n1 * n2 / 12 * ((n + 1) - tie_term)
    mu = n1 * n2 / 2
    if var <= 0:
        p, z = 1.0, 0.0
    else:
        z = (u1 - mu - 0.5 * (1 if u1 > mu else -1 if u1 < mu else 0)) / math.sqrt(var)  # corrección de continuidad
        p = _two_sided(z)
    effect = 1 - 2 * u1 / (n1 * n2)  # rango biserial: >0 ⇒ el periodo actual tarda más
    small = min(n1, n2) < MIN_N
    m1, m2 = _median(a), _median(b)
    verdict = _verdict(p, small)
    size = "pequeño" if abs(effect) < 0.3 else "moderado" if abs(effect) < 0.5 else "grande"
    direction = "más lento" if effect > 0 else "más rápido"
    if verdict == "sin_diferencia":
        text = (f"La mediana pasó de {_c(m1)} a {_c(m2)} días, pero la diferencia es compatible con el azar "
                f"({_p(p)}). No hay evidencia de que la remediación haya cambiado.")  # fmt: skip
    else:
        text = (f"La remediación fue {direction}: mediana de {_c(m1)} a {_c(m2)} días ({_p(p)}, efecto {size}, "
                f"r = {_c(effect, '+.2f')}).")  # fmt: skip
    if small:
        text += f" Ojo: hay pocos casos (anterior {n1}, actual {n2}); tómelo como indicio, no como conclusión."
    return {"test": "Mann-Whitney U", "n_prev": n1, "n_cur": n2, "median_prev": m1, "median_cur": m2,
            "p_value": round(p, 4), "z": round(z, 3), "effect": round(effect, 3), "verdict": verdict,
            "interpretation": text}  # fmt: skip


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def two_proportions(k1: int, n1: int, k2: int, n2: int) -> dict[str, Any]:
    """Cumplimiento de SLA: k de n mitigados a tiempo en el periodo anterior (1) y en el actual (2)."""
    if n1 == 0 or n2 == 0:
        return {"test": "z de dos proporciones", "n_prev": n1, "n_cur": n2, "p_value": None, "verdict": "sin_datos",
                "interpretation": "Falta un periodo con hallazgos mitigados: no se puede comparar el cumplimiento."}  # fmt: skip
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = 0.0 if se == 0 else (p2 - p1) / se
    p = 1.0 if se == 0 else _two_sided(z)
    small = min(n1, n2) < MIN_N
    verdict = _verdict(p, small)
    lo1, hi1 = wilson(k1, n1)
    lo2, hi2 = wilson(k2, n2)
    if verdict == "sin_diferencia":
        text = (f"El cumplimiento pasó de {p1 * 100:.0f} % a {p2 * 100:.0f} %, dentro de lo esperable por azar "
                f"({_p(p)}). No hay evidencia de un cambio real.")  # fmt: skip
    else:
        word = "mejoró" if p2 > p1 else "empeoró"
        text = f"El cumplimiento {word} de {p1 * 100:.0f} % a {p2 * 100:.0f} % ({_p(p)})."
    if small:
        text += f" Ojo: hay pocos casos (anterior {n1}, actual {n2}); el intervalo es muy ancho."
    return {"test": "z de dos proporciones", "n_prev": n1, "n_cur": n2, "pct_prev": round(p1 * 100, 1),
            "pct_cur": round(p2 * 100, 1), "ci_prev": [round(lo1 * 100, 1), round(hi1 * 100, 1)],
            "ci_cur": [round(lo2 * 100, 1), round(hi2 * 100, 1)], "p_value": round(p, 4), "z": round(z, 3),
            "verdict": verdict, "interpretation": text}  # fmt: skip


def mann_kendall(series: Sequence[float]) -> dict[str, Any]:
    """¿La serie diaria sube o baja de forma sostenida? (no supone linealidad ni normalidad)."""
    n = len(series)
    if n < 4:
        return {"test": "Mann-Kendall", "n": n, "p_value": None, "trend": "sin_datos", "slope_per_day": None,
                "interpretation": "Hay menos de 4 puntos: aún no se puede hablar de tendencia."}  # fmt: skip
    s = sum((series[j] > series[i]) - (series[j] < series[i]) for i in range(n - 1) for j in range(i + 1, n))
    _, ties = _ranks(list(series))
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in ties)) / 18
    z = 0.0 if var <= 0 or s == 0 else (s - (1 if s > 0 else -1)) / math.sqrt(var)
    p = 1.0 if z == 0 else _two_sided(z)
    slopes = sorted((series[j] - series[i]) / (j - i) for i in range(n - 1) for j in range(i + 1, n))
    m = len(slopes)
    slope = slopes[m // 2] if m % 2 else (slopes[m // 2 - 1] + slopes[m // 2]) / 2
    trend = "sin_tendencia" if p >= ALPHA else ("sube" if z > 0 else "baja")
    if trend == "sin_tendencia":
        text = f"No hay una tendencia sostenida en {n} días ({_p(p)}); las variaciones parecen ruido."
    else:
        text = (f"La serie {'sube' if trend == 'sube' else 'baja'} de forma sostenida: {_c(slope, '+.2f')} por día "
                f"({_p(p)}, {n} días).")  # fmt: skip
    return {"test": "Mann-Kendall", "n": n, "p_value": round(p, 4), "z": round(z, 3), "trend": trend,
            "slope_per_day": round(slope, 3), "interpretation": text}  # fmt: skip
