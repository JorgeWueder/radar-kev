import { defaultPeriod, reportError, reportParams, type ReportDef } from './reports'

const mttr: ReportDef = { key: 'mttr', kind: 'management', title: 'MTTR', description: '', period: true }
const cve: ReportDef = { key: 'cve_detail', kind: 'operational', title: 'CVE', description: '', period: false, needs_cve: true }
const period = { from: '2026-10-05', to: '2026-11-03' }

describe('reportes', () => {
  it('el periodo por defecto son los últimos 30 días', () => {
    expect(defaultPeriod(new Date(2026, 10, 3))).toEqual({ from: '2026-10-05', to: '2026-11-03' })
  })
  it('envía solo los parámetros que usa cada tipo', () => {
    expect(reportParams(mttr, 'pdf', period, '', true)).toEqual({ fmt: 'pdf', date_from: '2026-10-05', date_to: '2026-11-03', cve_id: undefined, ai_summary: true })
    expect(reportParams(cve, 'xlsx', period, ' cve-2021-44228 ', true)).toEqual({ fmt: 'xlsx', date_from: undefined, date_to: undefined, cve_id: 'CVE-2021-44228', ai_summary: undefined })
  })
  it('valida el periodo y el CVE antes de pedir el archivo', () => {
    expect(reportError(mttr, period, '')).toBeNull()
    expect(reportError(mttr, { from: '2026-11-10', to: '2026-11-01' }, '')).toMatch(/posterior/)
    expect(reportError(mttr, { from: '2024-01-01', to: '2026-11-01' }, '')).toMatch(/366/)
    expect(reportError(cve, period, 'no-es-cve')).toMatch(/CVE válido/)
    expect(reportError(cve, period, 'CVE-2021-44228')).toBeNull()
  })
})
