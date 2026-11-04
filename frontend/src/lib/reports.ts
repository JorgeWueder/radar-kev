export interface ReportDef {
  key: string
  kind: 'operational' | 'management'
  title: string
  description: string
  period: boolean
  needs_cve?: boolean
}

export type ReportFormat = 'pdf' | 'docx' | 'xlsx'

export const FORMAT_LABEL: Record<ReportFormat, string> = { pdf: 'PDF', docx: 'Word', xlsx: 'Excel' }

const pad = (n: number) => String(n).padStart(2, '0')
export const isoDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** Periodo por defecto: los últimos 30 días (incluye hoy). */
export function defaultPeriod(today = new Date()): { from: string; to: string } {
  const from = new Date(today)
  from.setDate(from.getDate() - 29)
  return { from: isoDate(from), to: isoDate(today) }
}

/** Parámetros de la petición de un reporte; solo se envía lo que ese tipo usa. */
export function reportParams(def: ReportDef, fmt: ReportFormat, period: { from: string; to: string }, cve: string, ai: boolean) {
  return {
    fmt,
    date_from: def.period ? period.from : undefined,
    date_to: def.period ? period.to : undefined,
    cve_id: def.needs_cve ? cve.trim().toUpperCase() : undefined,
    ai_summary: def.kind === 'management' && ai ? true : undefined,
  }
}

/** Validación previa en el cliente (el servidor vuelve a validar). */
export function reportError(def: ReportDef, period: { from: string; to: string }, cve: string): string | null {
  if (def.needs_cve && !/^CVE-\d{4}-\d{4,}$/i.test(cve.trim())) return 'Escriba un CVE válido, por ejemplo CVE-2021-44228'
  if (def.period) {
    if (period.from > period.to) return 'La fecha inicial no puede ser posterior a la final'
    const days = (Date.parse(period.to) - Date.parse(period.from)) / 86_400_000
    if (days > 366) return 'El periodo no puede superar 366 días'
  }
  return null
}
