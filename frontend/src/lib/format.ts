const LIMA = 'America/Lima'

const dateTime = new Intl.DateTimeFormat('es-PE', {
  timeZone: LIMA,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

/** Muestra un instante UTC (ISO) en hora de Lima: dd/mm/aaaa hh:mm:ss. */
export function formatLima(iso: string): string {
  const parts = Object.fromEntries(dateTime.formatToParts(new Date(iso)).map((p) => [p.type, p.value]))
  const hour = parts.hour === '24' ? '00' : parts.hour
  return `${parts.day}/${parts.month}/${parts.year} ${hour}:${parts.minute}:${parts.second}`
}

/** Convierte el valor de un <input type="datetime-local"> (hora de Lima, UTC-5 sin DST) a ISO UTC. */
export function limaInputToIso(value: string): string | undefined {
  if (!value) return undefined
  const d = new Date(`${value}${value.length === 16 ? ':00' : ''}-05:00`)
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString()
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms} ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s} s`
  return `${Math.floor(s / 60)} min ${s % 60} s`
}

/** 0.97312 → "97,3 %"; nulo → guion (los datos ausentes no se inventan). */
export function formatPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(digits).replace('.', ',')} %`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

/** Fecha de hoy en Lima como aaaa-mm-dd. */
export function limaToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: LIMA }).format(now)
}

/** Días enteros desde hoy (Lima) hasta una fecha aaaa-mm-dd: negativo si ya pasó, nulo si no hay fecha. */
export function daysUntil(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  const [ty, tm, td] = limaToday(now).split('-').map(Number)
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(ty, tm - 1, td)) / 86_400_000)
}

/** "vence en 3 días", "vence hoy", "vencido hace 2 días". */
export function dueText(days: number): string {
  if (days < 0) return `vencido hace ${-days} ${-days === 1 ? 'día' : 'días'}`
  if (days === 0) return 'vence hoy'
  if (days === 1) return 'vence mañana'
  return `vence en ${days} días`
}

/** Fracción (0 a 1) del plazo de SLA ya transcurrida entre la creación y el vencimiento (fin del día en Lima). */
export function slaProgress(createdIso: string, dueIso: string, now: number): number {
  const start = new Date(createdIso).getTime()
  const end = new Date(`${dueIso.slice(0, 10)}T23:59:59-05:00`).getTime()
  if (end <= start) return 1
  return Math.min(1, Math.max(0, (now - start) / (end - start)))
}
