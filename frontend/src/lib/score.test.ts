import { describe, expect, it } from 'vitest'

import { bandOf, riskScore } from './score'

const base = { ransomware: false, epss: 0.5, percentile: 0.9, cvss: 8, criticality: 3 }

describe('riskScore', () => {
  it('un CVE en KEV nunca baja del piso y uno fuera de KEV nunca lo alcanza', () => {
    expect(riskScore({ ...base, inKev: true, epss: 0, percentile: 0, cvss: 0, criticality: 1 })).toBeGreaterThanOrEqual(70)
    expect(riskScore({ ...base, inKev: false, epss: 1, percentile: 1, cvss: 10, criticality: 4 })).toBeLessThan(70)
  })
  it('suma el bono de ransomware con tope 100', () => {
    const top = { inKev: true, ransomware: true, epss: 1, percentile: 1, cvss: 10, criticality: 4 }
    expect(riskScore(top)).toBe(100)
    const a = riskScore({ ...base, inKev: true })
    const b = riskScore({ ...base, inKev: true, ransomware: true })
    expect(b - a).toBeCloseTo(5, 1)
  })
  it('asigna la banda según los umbrales', () => {
    expect(bandOf(85)).toBe('critical')
    expect(bandOf(70)).toBe('high')
    expect(bandOf(40)).toBe('medium')
    expect(bandOf(39.9)).toBe('low')
  })
})
