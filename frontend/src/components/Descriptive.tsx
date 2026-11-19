// Estadística descriptiva de los hallazgos abiertos (score, EPSS y CVSS), con su lectura en español.
import { CheckCircle, Info, Warning } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../lib/api'
import { Meta, Tabs } from './kit'
import { ErrorState, Panel, Skeleton, td, th } from './ui'

interface Summary { n: number; missing: number; mean: number | null; std: number | null; min: number | null; p25: number | null; median: number | null; p75: number | null; p90: number | null; max: number | null }
interface Variable { key: 'risk_score' | 'epss' | 'cvss'; label: string; unit: string; summary: Summary; distribution: { label: string; count: number }[]; interpretation: string[] }
interface GroupRow { group: string; label: string; n: number; kev: number; kev_pct: number | null; median_score: number | null; median_epss: number | null; median_cvss: number | null; small: boolean }
export interface Check { key: string; label: string; status: 'ok' | 'warn' | 'info'; count: number | null; detail: string }
interface Quality { status: 'ok' | 'warn'; checks: Check[]; interpretation: string[] }
interface Group { key: string; label: string; rows: GroupRow[]; interpretation: string[] }
export interface Descriptive {
  n: number; kev: number; interpretation: string[]; quality: Quality; how_to_read: { summary: string; distribution: string; groups: string }
  variables: Variable[]; groups: Group[]
  kev_vs_rest: { kev_n: number; rest_n: number; kev_median_epss: number | null; rest_median_epss: number | null; kev_median_cvss: number | null; rest_median_cvss: number | null; interpretation: string[] } | null
}

/** Número con coma decimal, sin ",0" sobrante; "—" si no hay dato. */
export function num(x: number | null | undefined, unit = '', digits = 1): string {
  if (x === null || x === undefined) return '—'
  const fixed = x.toFixed(digits).replace('.', ',')
  const s = digits === 1 ? fixed.replace(/,0$/, '') : fixed // con 2 decimales (AUC) se conservan: "1,00", no "1"
  return unit === '%' ? `${s} %` : s
}

function HowToRead({ children }: { children: string }) {
  return (
    <details className="mt-2 text-[12px] text-muted">
      <summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary>
      <p className="mt-1 max-w-prose">{children}</p>
    </details>
  )
}

function Notes({ items }: { items: string[] }) {
  if (!items.length) return null
  return <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px]">{items.map((t) => <li key={t}>{t}</li>)}</ul>
}

function Distribution({ v }: { v: Variable }) {
  const max = Math.max(1, ...v.distribution.map((b) => b.count))
  return (
    <figure aria-label={`Distribución de ${v.label} por tramos`}>
      <ul className="space-y-1.5">
        {v.distribution.map((b) => (
          <li key={b.label} className="grid grid-cols-[110px_1fr_32px] items-center gap-2 text-[12px]">
            <span className="truncate text-muted">{b.label}</span>
            <span className="h-2 rounded-sm bg-sunken" role="presentation"><span className="block h-2 rounded-sm bg-accent" style={{ width: `${(b.count / max) * 100}%` }} /></span>
            <span className="text-right tabular-nums">{b.count}</span>
          </li>
        ))}
      </ul>
    </figure>
  )
}

function SummaryTable({ v }: { v: Variable }) {
  const s = v.summary
  const cells: [string, string][] = [
    ['Con dato', String(s.n)], ['Sin dato', String(s.missing)], ['Mediana', num(s.median, v.unit)], ['Media', num(s.mean, v.unit)],
    ['Desv. estándar', num(s.std, v.unit)], ['P25 a P75', `${num(s.p25, v.unit)} a ${num(s.p75, v.unit)}`], ['P90', num(s.p90, v.unit)],
    ['Mín. a máx.', `${num(s.min, v.unit)} a ${num(s.max, v.unit)}`],
  ]
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] sm:grid-cols-4">
      {cells.map(([k, val]) => (
        <div key={k}><dt className="text-[12px] text-muted">{k}</dt><dd className="font-medium tabular-nums">{val}</dd></div>
      ))}
    </dl>
  )
}

function GroupTable({ g }: { g: Group }) {
  return (
    <div>
      <h3 className="px-4 pt-3 text-[13px] font-semibold">{g.label}</h3>
      <div className="overflow-x-auto">
        <table className="mt-1 w-full text-[13px]">
          <thead>
            <tr>
              <th className={th}>Grupo</th><th className={`${th} text-right`}>Hallazgos</th><th className={`${th} text-right`}>En KEV</th>
              <th className={`${th} text-right`}>Mediana score</th><th className={`${th} text-right`}>Mediana EPSS</th><th className={`${th} text-right`}>Mediana CVSS</th>
            </tr>
          </thead>
          <tbody>
            {g.rows.map((r) => (
              <tr key={r.group}>
                <td className={td}>{r.label}{r.small && <span className="ml-2"><Meta>orientativo</Meta></span>}</td>
                <td className={`${td} text-right tabular-nums`}>{r.n}</td>
                <td className={`${td} text-right tabular-nums`}>{r.kev} <span className="text-muted">({num(r.kev_pct, '%', 0)})</span></td>
                <td className={`${td} text-right tabular-nums`}>{num(r.median_score)}</td>
                <td className={`${td} text-right tabular-nums`}>{num(r.median_epss, '%')}</td>
                <td className={`${td} text-right tabular-nums`}>{num(r.median_cvss)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="px-4 pb-3"><Notes items={g.interpretation} /></div>
    </div>
  )
}

const CHECK_ICON = { ok: [CheckCircle, 'text-muted', 'Correcto'], warn: [Warning, 'text-warn', 'Aviso'], info: [Info, 'text-muted', 'Información'] } as const
/** Adónde ir para corregir cada aviso. */
const FIX: Record<string, [string, string]> = {
  assumed_criticality: ['/activos', 'Completar activos'],
  epss_age: ['/ejecuciones', 'Ver ejecuciones'],
  missing_epss: ['/ejecuciones', 'Ver ejecuciones'],
}

function CheckItem({ c }: { c: Check }) {
  const [Icon, tone, word] = CHECK_ICON[c.status]
  const fix = c.status === 'warn' ? FIX[c.key] : undefined
  return (
    <li className="grid grid-cols-[18px_1fr] gap-2 py-1.5 text-[13px]">
      <Icon size={16} weight={c.status === 'warn' ? 'bold' : 'regular'} className={`mt-0.5 ${tone}`} aria-label={word} />
      <span>
        <span className="font-medium">{c.label}.</span> {c.detail}
        {fix && <> <Link to={fix[0]} className="whitespace-nowrap font-medium text-link hover:underline">{fix[1]}</Link></>}
      </span>
    </li>
  )
}

/** Validación de datos y grupos antes de la estadística: los avisos se muestran; lo correcto queda plegado. */
export function QualityBlock({ q }: { q: Quality }) {
  if (!q.checks.length) return null
  const warn = q.checks.filter((c) => c.status === 'warn')
  const rest = q.checks.filter((c) => c.status !== 'warn')
  return (
    <div className={`mb-4 rounded-lg border p-3 ${warn.length ? 'border-warn/40 bg-warn-soft' : 'border-line bg-sunken'}`} role="region" aria-label="Calidad de los datos">
      <p className="flex items-center gap-2 text-[13px] font-semibold">
        {warn.length ? <Warning size={16} weight="bold" className="text-warn" aria-hidden /> : <CheckCircle size={16} className="text-muted" aria-hidden />}
        Calidad de los datos
      </p>
      <p className="mt-0.5 text-[12px] text-muted">{q.interpretation.join(' ')}</p>
      {warn.length > 0 && <ul className="mt-1">{warn.map((c) => <CheckItem key={c.key} c={c} />)}</ul>}
      {rest.length > 0 && (
        <details className="mt-1 text-[12px] text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">{rest.length} {rest.length === 1 ? 'validación correcta o informativa' : 'validaciones correctas o informativas'}</summary>
          <ul className="mt-1 text-ink">{rest.map((c) => <CheckItem key={c.key} c={c} />)}</ul>
        </details>
      )}
    </div>
  )
}

export function DescriptivePanel() {
  const [key, setKey] = useState<Variable['key']>('risk_score')
  const q = useQuery({ queryKey: ['dash-descriptive'], queryFn: () => api.get<Descriptive>('/dashboard/descriptive') })
  if (q.isPending) return <Panel className="mt-4 p-4"><Skeleton cols={2} rows={4} /></Panel>
  if (q.isError) return <Panel className="mt-4"><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></Panel>
  const d = q.data
  if (!d.variables.length) return null
  const v = d.variables.find((x) => x.key === key) ?? d.variables[0]
  const kv = d.kev_vs_rest
  return (
    <section aria-labelledby="desc-title" className="mt-4">
      <Panel className="p-4">
        <h2 id="desc-title" className="text-[14px] font-semibold">Perfil del inventario: estadística descriptiva</h2>
        <p className="mb-3 text-[12px] text-muted">{d.interpretation.join(' ')} Solo describe los hallazgos abiertos; la prioridad la fija el score.</p>
        <QualityBlock q={d.quality} />
        <Tabs label="Variable" value={v.key} onChange={setKey} tabs={d.variables.map((x) => ({ id: x.key, label: x.label }))} />
        <div id={`panel-${v.key}`} role="tabpanel" aria-labelledby={`tab-${v.key}`} className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <SummaryTable v={v} />
            <Notes items={v.interpretation} />
            <HowToRead>{d.how_to_read.summary}</HowToRead>
          </div>
          <div>
            <h3 className="mb-2 text-[13px] font-semibold">Distribución por tramos</h3>
            <Distribution v={v} />
            <HowToRead>{d.how_to_read.distribution}</HowToRead>
          </div>
        </div>
      </Panel>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr]">
        {d.groups.map((g) => <Panel key={g.key}><GroupTable g={g} /></Panel>)}
      </div>

      {kv && (
        <Panel className="mt-4 p-4">
          <h3 className="text-[13px] font-semibold">En KEV frente al resto</h3>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] sm:grid-cols-3">
            <div><dt className="text-[12px] text-muted">Hallazgos</dt><dd className="font-medium tabular-nums">{kv.kev_n} en KEV · {kv.rest_n} resto</dd></div>
            <div><dt className="text-[12px] text-muted">Mediana EPSS</dt><dd className="font-medium tabular-nums">{num(kv.kev_median_epss, '%')} · {num(kv.rest_median_epss, '%')}</dd></div>
            <div><dt className="text-[12px] text-muted">Mediana CVSS</dt><dd className="font-medium tabular-nums">{num(kv.kev_median_cvss)} · {num(kv.rest_median_cvss)}</dd></div>
          </dl>
          <Notes items={kv.interpretation} />
          <HowToRead>{d.how_to_read.groups}</HowToRead>
        </Panel>
      )}
    </section>
  )
}
