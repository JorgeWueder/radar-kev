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
