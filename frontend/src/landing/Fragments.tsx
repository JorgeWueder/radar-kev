// Fragmentos de la interfaz real del radar, con datos de demostración. Los puntajes salen de la misma fórmula del backend.
import { motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'

import { bandOf, BAND_LABEL, riskScore, type Band } from '../lib/score'

const EASE = [0.23, 1, 0.32, 1] as const

const BAND_CLASS: Record<Band, string> = {
  critical: 'bg-danger-soft text-danger',
  high: 'bg-warn-soft text-warn',
  medium: 'bg-sunken text-ink',
  low: 'bg-ok-soft text-ok',
}

export function BandTag({ band }: { band: Band }) {
  return <span className={`inline-block rounded px-1.5 py-0.5 text-[13px] font-medium ${BAND_CLASS[band]}`}>{BAND_LABEL[band]}</span>
}

interface Row {
  cve: string
  host: string
  crit: number
  inKev: boolean
  epss: number
  cvss: number
  ransomware?: boolean
  due: string
}

const ROWS: Row[] = [
  { cve: 'CVE-2024-3400', host: 'fw-borde-01', crit: 4, inKev: true, epss: 0.94, cvss: 10, due: 'Vence en 3 días' },
  { cve: 'CVE-2023-4966', host: 'vpn-sede', crit: 4, inKev: true, epss: 0.97, cvss: 9.4, ransomware: true, due: 'Vence en 9 días' },
  { cve: 'CVE-2021-44228', host: 'app-pagos', crit: 3, inKev: true, epss: 0.94, cvss: 10, due: 'En plazo' },
  { cve: 'CVE-2023-38545', host: 'ws-contabilidad', crit: 2, inKev: false, epss: 0.07, cvss: 9.8, due: 'En plazo' },
  { cve: 'CVE-2022-22965', host: 'dev-sandbox', crit: 1, inKev: false, epss: 0.03, cvss: 9.8, due: 'En plazo' },
]

const SCORED = ROWS.map((r) => {
  const score = riskScore({ inKev: r.inKev, ransomware: !!r.ransomware, epss: r.epss, percentile: Math.min(1, r.epss + 0.04), cvss: r.cvss, criticality: r.crit })
  return { ...r, score, band: bandOf(score) }
}).sort((a, b) => b.score - a.score)

const SEP = 'border-t border-line' // taste-skill-ignore: fragmento de interfaz real
const shell = 'w-full overflow-hidden rounded-[20px] border border-line bg-surface text-[14px] text-ink'

export function RankingFragment({ compact = false }: { compact?: boolean }) {
  const rows = compact ? SCORED.slice(0, 3) : SCORED
  return (
    <div data-ui className={shell}>
      <div className="flex items-center justify-between bg-sunken px-3 py-2">
        <span className="font-medium">Vulnerabilidades priorizadas</span>
        <span className="text-muted">Hoy</span>
      </div>
      <ul>
        {rows.map((r) => (
          <li key={r.cve} className={`grid grid-cols-[1fr_auto] items-center gap-x-3 ${SEP} px-3 py-2`}>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2">
                <span className="font-medium">{r.cve}</span>
                {r.inKev && <span className="rounded bg-danger px-1.5 text-[13px] font-medium text-bg">KEV</span>}
                {r.ransomware && <span className="text-[13px] text-danger">Ransomware</span>}
              </div>
              <div className="truncate text-[13px] text-muted">
                {r.host} · EPSS {Math.round(r.epss * 100)} % · CVSS {r.cvss}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[20px] font-semibold leading-none tabular-nums">{Math.round(r.score)}</div>
              <BandTag band={r.band} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* Lista de la portada: aparece ordenada por CVSS y, a los 1,5 s, se reordena por puntaje con animación de layout (una sola vez). */
export function RankingLive() {
  const reduce = useReducedMotion()
  const [byScore, setByScore] = useState(!!reduce)
  useEffect(() => {
    if (reduce) return
    const t = setTimeout(() => setByScore(true), 1500)
    return () => clearTimeout(t)
  }, [reduce])
  const rows = byScore ? SCORED : [...SCORED].sort((a, b) => b.cvss - a.cvss)
  return (
    <div data-ui className={shell}>
      <div className="flex items-center justify-between bg-sunken px-3 py-2">
        <span className="font-medium">Vulnerabilidades priorizadas</span>
        <span className="text-muted" aria-live="polite">
          {byScore ? 'Orden del radar' : 'Orden por CVSS'}
        </span>
      </div>
      <ul>
        {rows.map((r) => (
          <motion.li key={r.cve} layout="position" transition={{ duration: 0.6, ease: EASE }} className={`grid grid-cols-[1fr_auto] items-center gap-x-3 ${SEP} bg-surface px-3 py-2`}>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2">
                <span className="font-medium">{r.cve}</span>
                {r.inKev && <span className="rounded bg-danger px-1.5 text-[13px] font-medium text-bg">KEV</span>}
                {r.ransomware && <span className="text-[13px] text-danger">Ransomware</span>}
              </div>
              <div className="truncate text-[13px] text-muted">
                {r.host} · EPSS {Math.round(r.epss * 100)} % · CVSS {r.cvss}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[20px] font-semibold leading-none tabular-nums">{Math.round(r.score)}</div>
              <BandTag band={r.band} />
            </div>
          </motion.li>
        ))}
      </ul>
    </div>
  )
}

export function RunFragment() {
  const stats: Array<[string, string]> = [
    ['Coincidencias nuevas', '2'],
    ['Alertas y tickets', '2'],
    ['Correos enviados', '1'],
  ]
  return (
    <div data-ui className={shell}>
      <div className="flex items-center justify-between bg-sunken px-3 py-2">
        <span className="font-medium">Ejecución diaria</span>
        <span className="rounded bg-ok-soft px-1.5 text-[13px] font-medium text-ok">Completada</span>
      </div>
      <dl className="grid grid-cols-3 gap-2 px-3 py-3">
        {stats.map(([k, v]) => (
          <div key={k}>
            <dd className="text-[28px] font-semibold leading-none tabular-nums">{v}</dd>
            <dt className="mt-1 text-[13px] leading-tight text-muted">{k}</dt>
          </div>
        ))}
      </dl>
      <p className={`${SEP} px-3 py-2 text-[13px] text-muted`}>La segunda ejecución del día no repite alertas.</p>
    </div>
  )
}

export function TicketFragment() {
  const top = SCORED[0]
  return (
    <div data-ui className={shell}>
      <div className="flex items-center justify-between bg-sunken px-3 py-2">
        <span className="font-medium">Ticket · {top.cve}</span>
        <BandTag band={top.band} />
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 px-3 py-3 text-[13px]">
        <div>
          <dt className="text-muted">Activo</dt>
          <dd className="text-[14px] font-medium">{top.host}</dd>
        </div>
        <div>
          <dt className="text-muted">Plazo (SLA)</dt>
          <dd className="text-[14px] font-medium text-warn">{top.due}</dd>
        </div>
        <div>
          <dt className="text-muted">Estado</dt>
          <dd className="text-[14px] font-medium">Abierto</dd>
        </div>
        <div>
          <dt className="text-muted">Score</dt>
          <dd className="text-[14px] font-medium tabular-nums">{top.score.toFixed(1)}</dd>
        </div>
      </dl>
      <div className={`flex gap-2 ${SEP} px-3 py-2 text-[13px]`}>
        <span className="rounded-full bg-control px-3 py-1">Resolver</span>
        <span className="rounded-full bg-control px-3 py-1">Aceptar riesgo</span>
      </div>
    </div>
  )
}

export function EpssFragment() {
  return (
    <div data-ui className={shell}>
      <div className="px-3 py-3">
        <div className="flex items-baseline justify-between">
          <span className="font-medium">EPSS</span>
          <span className="text-[20px] font-semibold tabular-nums">94 %</span>
        </div>
        <div className="mt-2 h-2 rounded-full bg-sunken">
          <div className="h-2 w-[94%] rounded-full bg-accent" />
        </div>
        <p className="mt-2 text-[13px] text-muted">Probabilidad de explotación en los próximos 30 días.</p>
      </div>
    </div>
  )
}

export function CvssFragment() {
  return (
    <div data-ui className={shell}>
      <div className="grid grid-cols-2 gap-3 px-3 py-3">
        <div>
          <div className="text-[28px] font-semibold leading-none tabular-nums">9.8</div>
          <div className="mt-1 text-[13px] text-muted">CVSS: muy grave</div>
        </div>
        <div>
          <div className="text-[28px] font-semibold leading-none tabular-nums">3 %</div>
          <div className="mt-1 text-[13px] text-muted">EPSS: casi nadie la usa</div>
        </div>
      </div>
    </div>
  )
}

export function KevFragment() {
  return (
    <div data-ui className={shell}>
      <div className="px-3 py-3">
        <div className="flex items-center justify-between">
          <span className="font-medium">CVE-2021-44228</span>
          <span className="rounded bg-danger px-1.5 text-[13px] font-medium text-bg">En KEV</span>
        </div>
        <p className="mt-1 text-[13px] text-muted">Explotación activa confirmada por CISA. Tiene fecha límite de remediación.</p>
      </div>
    </div>
  )
}

export function InventoryFragment() {
  const items: Array<[string, string]> = [
    ['fw-borde-01', 'Crítica · Producción'],
    ['app-pagos', 'Alta · Producción'],
    ['dev-sandbox', 'Baja · Desarrollo'],
  ]
  return (
    <div data-ui className={shell}>
      <ul>
        {items.map(([h, c], i) => (
          <li key={h} className={`flex items-center justify-between px-3 py-2 ${i ? SEP : ''}`}>
            <span className="font-medium">{h}</span>
            <span className="text-[13px] text-muted">{c}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function FormulaFragment() {
  return (
    <div data-ui className={shell}>
      <div className="px-3 py-3 text-[13px] leading-relaxed">
        <p className="font-medium text-[14px]">En KEV</p>
        <p className="text-muted">70 + 30 × base (+5 si hay ransomware), tope 100</p>
        <p className="mt-2 font-medium text-[14px]">Fuera de KEV</p>
        <p className="text-muted">69 × base, siempre por debajo de 70</p>
      </div>
    </div>
  )
}

/* Dos CVE con la misma gravedad técnica y prioridades opuestas: el argumento central del radar. */
const A = { inKev: false, ransomware: false, epss: 0.03, percentile: 0.35, cvss: 9.8, criticality: 3 }
const B = { inKev: true, ransomware: false, epss: 0.91, percentile: 0.99, cvss: 7.2, criticality: 3 }

function Bar({ value, on, delay = 0 }: { value: number; on: boolean; delay?: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-line" aria-hidden>
      <motion.div className="h-full origin-left rounded-full bg-ink" initial={false} animate={{ scaleX: on ? value : 0 }} transition={{ duration: 0.7, ease: EASE, delay }} />
    </div>
  )
}

function Case({ cve, i, note, bars }: { cve: string; i: typeof A; note: string; bars: boolean }) {
  const score = riskScore(i)
  const band = bandOf(score)
  return (
    <div className="flex flex-col gap-4 p-5 md:p-7">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[20px] font-medium">{cve}</span>
        {i.inKev ? <span className="rounded bg-danger px-2 py-0.5 text-[14px] font-medium text-bg">En KEV</span> : <span className="text-[14px] text-muted">Fuera de KEV</span>}
      </div>
      <dl className="grid grid-cols-3 gap-3 text-[14px] text-muted">
        <div>
          <dd className="text-[clamp(26px,3vw,40px)] font-semibold leading-none text-ink tabular-nums">{i.cvss}</dd>
          <dt className="mt-1">CVSS</dt>
        </div>
        <div>
          <dd className="text-[clamp(26px,3vw,40px)] font-semibold leading-none text-ink tabular-nums">{Math.round(i.epss * 100)} %</dd>
          <dt className="mt-1">EPSS</dt>
        </div>
        <div>
          <dd className="text-[clamp(26px,3vw,40px)] font-semibold leading-none text-ink tabular-nums">{Math.round(score)}</dd>
          <dt className="mt-1">Puntaje</dt>
        </div>
      </dl>
      <div className="space-y-2">
        <Bar value={i.cvss / 10} on={bars} />
        <Bar value={i.epss} on={bars} delay={0.12} />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-[16px]">
        <BandTag band={band} />
        <span>{note}</span>
      </div>
    </div>
  )
}

/* Las barras de CVSS y EPSS se llenan y, después, las tarjetas intercambian lugar: del orden por gravedad al orden del radar. */
export function ComparisonFragment() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, margin: '0px 0px -15% 0px' })
  const reduce = useReducedMotion()
  const [swapped, setSwapped] = useState(!!reduce)
  const bars = inView || !!reduce
  useEffect(() => {
    if (!inView || reduce) return
    const t = setTimeout(() => setSwapped(true), 1800)
    return () => clearTimeout(t)
  }, [inView, reduce])

  const cards = [
    { id: 'A', node: <Case cve="CVE-2023-38545" i={A} note="Grave en el papel; casi nadie la usa." bars={bars} />, cls: '' },
    { id: 'B', node: <Case cve="CVE-2021-44228" i={B} note="Menos grave, pero ya la explotan." bars={bars} />, cls: 'bg-sunken' },
  ]
  const ordered = swapped ? [cards[1], cards[0]] : cards
  return (
    <div ref={ref} data-ui className="w-full overflow-hidden rounded-[28px] border border-line bg-surface text-ink">
      <p className="px-5 pt-4 text-[14px] text-muted md:px-7" aria-live="polite">
        {swapped ? 'Orden del radar: primero lo que ya se explota' : 'Orden por gravedad (CVSS)'}
      </p>
      <div className="grid md:grid-cols-2">
        {ordered.map((c) => (
          <motion.div key={c.id} layout="position" transition={{ duration: 0.7, ease: EASE }} className={c.cls}>
            {c.node}
          </motion.div>
        ))}
      </div>
    </div>
  )
}
