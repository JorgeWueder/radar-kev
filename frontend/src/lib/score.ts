// Réplica de backend/app/services/scoring.py con los parámetros por defecto, para la calculadora del sitio público.
// La fuente de verdad sigue siendo el backend; esto solo ilustra la fórmula.

export const PARAMS = {
  wEpss: 0.35,
  wPercentile: 0.15,
  wCvss: 0.25,
  wAsset: 0.25,
  kevFloor: 70,
  ransomwareBonus: 5,
  bandCritical: 85,
  bandHigh: 70,
  bandMedium: 40,
  sla: { critical: 15, high: 30, medium: 90, low: 180 },
} as const

export type Band = 'critical' | 'high' | 'medium' | 'low'

export interface ScoreInput {
  inKev: boolean
  ransomware: boolean
  epss: number // 0..1
  percentile: number // 0..1
  cvss: number // 0..10
  criticality: number // 1..4
}

export function riskScore(i: ScoreInput): number {
  const p = PARAMS
  const base = p.wEpss * i.epss + p.wPercentile * i.percentile + p.wCvss * (i.cvss / 10) + p.wAsset * (i.criticality / 4)
  if (i.inKev) {
    const score = p.kevFloor + (100 - p.kevFloor) * base + (i.ransomware ? p.ransomwareBonus : 0)
    return Math.round(Math.min(100, score) * 100) / 100
  }
  return Math.round((p.kevFloor - 1) * base * 100) / 100
}

export function bandOf(score: number): Band {
  if (score >= PARAMS.bandCritical) return 'critical'
  if (score >= PARAMS.bandHigh) return 'high'
  if (score >= PARAMS.bandMedium) return 'medium'
  return 'low'
}

export const BAND_LABEL: Record<Band, string> = { critical: 'Crítica', high: 'Alta', medium: 'Media', low: 'Baja' }
