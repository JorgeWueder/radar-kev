// Fase 4 · Explicabilidad: importancia por permutación, dependencia parcial 1D/2D, oclusión por caso y coeficientes.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts'

import { api } from '../../lib/api'
import { num } from '../Descriptive'
import { Tabs } from '../kit'
import { EmptyState, ErrorState, Field, Panel, Select, Skeleton, td, th } from '../ui'
import { JobProgress } from './JobProgress'
import type { Model } from './Training'
import type { Dataset } from './types'

interface Imp { name: string; kind: 'grupo' | 'variable'; mean: number; sd: number }
interface Attr { group: string; delta: number }
interface Case { cve: string; snapshot: string; label: number; prob: number; values: Record<string, string | number | null>; attributions: Attr[] }
export interface Explanation {
  model: { id: string; name: string; algorithm: string }; drop: string[]
  importance: { base_roc_auc: number; rows: Imp[] }
  pdp: { feature: string; points: { x: number; y: number }[] }[]
  pdp2d: { x: string; y: string; xs: number[]; ys: number[]; cells: { x: number; y: number; p: number }[] } | null
  local: Record<'aciertos' | 'escapados' | 'falsas_alarmas', Case[]>
  coefficients: { feature: string; coef: number }[]
  equivalences: { promptuario: string; aqui: string; porque: string }[]
  interpretation: string[]; how_to_read: Record<string, string>
}
interface Computing { status: 'computing'; job_id: string }

type CaseTab = 'aciertos' | 'escapados' | 'falsas_alarmas'
const CASE_TABS: { id: CaseTab; label: string }[] = [
  { id: 'aciertos', label: 'Aciertos (KEV con mayor probabilidad)' }, { id: 'escapados', label: 'KEV que se escaparon' }, { id: 'falsas_alarmas', label: 'Falsas alarmas' },
]
const FEATURE_LABEL: Record<string, string> = {
  epss: 'EPSS', percentile: 'Percentil EPSS', epss_delta: 'Cambio de EPSS', cvss: 'CVSS de la CNA', days_published: 'Días desde la publicación',
  edb_exploits: 'Exploits públicos', cna_kev_prior: 'KEV previos de la CNA',
}
const fx = (f: string) => FEATURE_LABEL[f] ?? f
/** Puntos porcentuales con decimales según la magnitud (+20 pp, +0,012 pp). */
const pp = (d: number) => `${d > 0 ? '+' : ''}${num(100 * d, '', Math.abs(100 * d) >= 1 ? 1 : 3)} pp`

function How({ children }: { children?: string }) {
  if (!children) return null
  return <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{children}</p></details>
}

function Bars({ rows }: { rows: Imp[] }) {
  const max = Math.max(1e-6, ...rows.map((r) => r.mean))
  return (
    <ul className="space-y-1.5">
      {rows.map((r) => (
        <li key={r.name} className="grid grid-cols-[minmax(0,190px)_1fr_92px] items-center gap-2 text-[12px]">
          <span className="truncate" title={r.name}>{fx(r.name)}</span>
          <span className="h-2 rounded-sm bg-sunken" role="presentation"><span className="block h-2 rounded-sm bg-accent" style={{ width: `${Math.max(0, r.mean / max) * 100}%` }} /></span>
          <span className="text-right tabular-nums">{num(r.mean, '', 3)} <span className="text-muted">± {num(r.sd, '', 3)}</span></span>
        </li>
      ))}
    </ul>
  )
}

function Heatmap({ m }: { m: NonNullable<Explanation['pdp2d']> }) {
  const ps = m.cells.map((c) => c.p)
  const lo = Math.min(...ps)
  const hi = Math.max(...ps)
  const rows = [...m.ys].reverse()
  return (
    <figure aria-label={`Mapa de interacción entre ${fx(m.x)} y ${fx(m.y)}: probabilidad media de ${num(100 * lo, '%', 3)} a ${num(100 * hi, '%', 3)}`}>
      <div className="grid gap-2" style={{ gridTemplateColumns: 'auto 1fr' }}>
        <div className="flex items-center"><span className="-rotate-180 text-[11px] text-muted [writing-mode:vertical-rl]">{fx(m.y)}</span></div>
        <div>
          <div className="grid gap-px" style={{ gridTemplateColumns: `56px repeat(${m.xs.length}, minmax(0, 1fr))` }}>
            {rows.map((vy) => (
              <div key={vy} className="contents">
                <span className="pr-1 text-right text-[10px] tabular-nums text-muted">{num(vy, '', vy < 1 ? 3 : 0)}</span>
                {m.xs.map((vx) => {
                  const p = m.cells.find((c) => c.x === vx && c.y === vy)?.p ?? lo
                  const t = hi > lo ? (p - lo) / (hi - lo) : 0
                  return <span key={vx} className="h-6 rounded-sm bg-accent" style={{ opacity: 0.08 + 0.92 * t }} title={`${fx(m.x)} ${num(vx, '', 3)} · ${fx(m.y)} ${num(vy, '', 3)}: ${num(100 * p, '%', 3)}`} />
                })}
              </div>
            ))}
            <span />
            {m.xs.map((vx) => <span key={vx} className="truncate text-center text-[10px] tabular-nums text-muted">{num(vx, '', vx < 1 ? 3 : 0)}</span>)}
          </div>
          <p className="mt-1 text-center text-[11px] text-muted">{fx(m.x)}</p>
        </div>
      </div>
      <figcaption className="mt-1 flex items-center gap-2 text-[12px] text-muted">
        <span className="tabular-nums">{num(100 * lo, '%', 3)}</span>
        <span className="h-2 w-24 rounded-sm bg-gradient-to-r from-sunken to-accent" aria-hidden />
        <span className="tabular-nums">{num(100 * hi, '%', 3)}</span>
        <span>probabilidad media</span>
      </figcaption>
    </figure>
  )
}

function CaseCard({ c }: { c: Case }) {
  const max = Math.max(1e-9, ...c.attributions.map((a) => Math.abs(a.delta)))
  const v = c.values
  return (
    <li className="rounded-lg border border-line p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-mono text-[13px] font-medium">{c.cve}</span>
        <span className="text-[12px] text-muted">foto {c.snapshot.slice(0, 7)} · {c.label ? 'entró a KEV' : 'no entró'} · puntaje del modelo <span className="font-medium text-ink tabular-nums">{num(100 * c.prob, '%', 2)}</span></span>
      </div>
      <p className="mt-1 text-[12px] text-muted">
        EPSS {num(v.epss as number | null, '', 4)} · CVSS {v.cvss ?? '—'} · {v.days_published ?? '—'} días · CNA <span className="font-mono">{String(v.cna ?? '—')}</span> · {String(v.cwe ?? '—')} · exploits {v.edb_exploits ?? 0}
      </p>
      <ul className="mt-2 space-y-1" aria-label={`Atribución por oclusión de ${c.cve}`}>
        {c.attributions.map((a) => (
          <li key={a.group} className="grid grid-cols-[minmax(0,170px)_1fr_1fr_70px] items-center gap-1 text-[12px]">
            <span className="truncate">{a.group}</span>
            <span className="flex justify-end">{a.delta < 0 && <span className="h-2 rounded-sm bg-muted" style={{ width: `${(Math.abs(a.delta) / max) * 100}%` }} />}</span>
            <span>{a.delta > 0 && <span className="block h-2 rounded-sm bg-accent" style={{ width: `${(a.delta / max) * 100}%` }} />}</span>
            <span className="text-right tabular-nums">{pp(a.delta)}</span>
          </li>
        ))}
      </ul>
    </li>
  )
}

export function LabExplain({ datasets }: { datasets: Dataset[] }) {
  const ready = datasets.filter((d) => d.status === 'ready')
  const preferred = ready.find((d) => !d.tags.includes('descartado')) ?? ready[0]
  const [dsId, setDsId] = useState<string | null>(null)
  const datasetId = dsId ?? preferred?.id ?? null
  const models = useQuery({ queryKey: ['ml-models', datasetId], queryFn: () => api.get<Model[]>('/ml/models', { dataset_id: datasetId ?? '' }), enabled: !!datasetId })
  const readyModels = (models.data ?? []).filter((m) => m.status === 'ready')
  const [picked, setPicked] = useState<string | null>(null)
  const modelId = picked ?? readyModels[0]?.id ?? null
  const q = useQuery({ queryKey: ['ml-explain', modelId], queryFn: () => api.get<Explanation | Computing>(`/ml/models/${modelId}/explanation`), enabled: !!modelId, retry: false })
  const [view, setView] = useState<'grupo' | 'variable'>('grupo')
  const [feature, setFeature] = useState<string | null>(null)
  const [caseTab, setCaseTab] = useState<CaseTab>('aciertos')
  if (!ready.length) return <Panel><EmptyState title="Aún no hay datasets listos" hint="Construya uno en la fase 1 · Datos." /></Panel>
  const computing = q.data && 'status' in q.data ? q.data : null
  const r = q.data && !('status' in q.data) ? q.data : undefined
  const pdpRow = r?.pdp.find((d) => d.feature === feature) ?? r?.pdp[0]

  return (
    <div className="space-y-4">
      <Panel className="flex flex-wrap items-end gap-4 p-4">
        <div className="w-64"><Field label="Dataset"><Select value={datasetId ?? ''} onChange={(e) => { setDsId(e.target.value); setPicked(null) }}>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field></div>
        <div className="w-80"><Field label="Modelo"><Select value={modelId ?? ''} onChange={(e) => setPicked(e.target.value)} disabled={!readyModels.length}>{readyModels.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field></div>
        <p className="max-w-prose text-[12px] text-muted">Se explica el modelo final sobre la partición de prueba.</p>
      </Panel>

      {!readyModels.length && !models.isPending ? <Panel><EmptyState title="Aún no hay modelos entrenados" hint="Entrene uno en la fase 2." /></Panel>
        : q.isPending ? <Panel className="p-4"><Skeleton cols={3} rows={5} /></Panel>
        : q.isError ? <Panel><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></Panel>
        : computing ? (
          <Panel className="p-4">
            <h2 className="mb-2 text-[14px] font-semibold">Calculando las explicaciones</h2>
            <JobProgress jobId={computing.job_id} onDone={() => void q.refetch()} />
          </Panel>
        ) : r && (
        <>
          <Panel className="p-4">
            <h2 className="text-[14px] font-semibold">Equivalencias con el Promptuario</h2>
            <p className="mb-2 text-[12px] text-muted">Grad-CAM++, los mapas de atención y las máscaras son técnicas para imágenes; estos son sus equivalentes para datos tabulares.</p>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead><tr><th className={th}>Promptuario</th><th className={th}>Aquí</th><th className={th}>Por qué es equivalente</th></tr></thead>
                <tbody>{r.equivalences.map((e) => <tr key={e.promptuario}><td className={`${td} whitespace-nowrap font-medium`}>{e.promptuario}</td><td className={`${td} whitespace-nowrap`}>{e.aqui}</td><td className={`${td} min-w-[260px]`}>{e.porque}</td></tr>)}</tbody>
              </table>
            </div>
            <h3 className="mt-4 text-[13px] font-semibold">Lectura de los resultados</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px]">{r.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>
          </Panel>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel className="min-w-0 p-4">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-[14px] font-semibold">Importancia global (mapa de atención)</h2>
                <div role="group" aria-label="Nivel de detalle" className="flex gap-1">
                  {(['grupo', 'variable'] as const).map((k) => (
                    <button key={k} type="button" aria-pressed={view === k} onClick={() => setView(k)}
                      className={`h-7 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-10 ${view === k ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>{k === 'grupo' ? 'Por grupo' : 'Por variable'}</button>
                  ))}
                </div>
              </div>
              <p className="mb-2 text-[12px] text-muted">Caída del ROC-AUC en prueba (base {num(r.importance.base_roc_auc, '', 3)}) al desordenar cada {view}.</p>
              <Bars rows={r.importance.rows.filter((x) => x.kind === view)} />
              <How>{r.how_to_read.importance}</How>
            </Panel>
            <Panel className="min-w-0 p-4">
              <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                <h2 className="text-[14px] font-semibold">Dependencia parcial</h2>
                <div className="w-56"><Select aria-label="Variable" value={pdpRow?.feature ?? ''} onChange={(e) => setFeature(e.target.value)}>{r.pdp.map((d) => <option key={d.feature} value={d.feature}>{fx(d.feature)}</option>)}</Select></div>
              </div>
              {pdpRow && (
                <figure aria-label={`Dependencia parcial de ${fx(pdpRow.feature)}`}>
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={pdpRow.points} margin={{ top: 6, right: 14, bottom: 14, left: -4 }}>
                      <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
                      <XAxis dataKey="x" type="number" domain={['dataMin', 'dataMax']} tickFormatter={(v: number) => num(v, '', v < 1 ? 3 : 0)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false}
                        label={{ value: fx(pdpRow.feature), position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
                      <YAxis tickFormatter={(v: number) => num(100 * v, '%', 2)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} width={56} />
                      <Line dataKey="y" stroke="var(--accent)" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </figure>
              )}
              <How>{r.how_to_read.pdp}</How>
            </Panel>
          </div>

          {r.pdp2d && (
            <Panel className="p-4">
              <h2 className="mb-2 text-[14px] font-semibold">Mapa de interacción: {fx(r.pdp2d.x)} × {fx(r.pdp2d.y)}</h2>
              <Heatmap m={r.pdp2d} />
              <How>{r.how_to_read.pdp2d}</How>
            </Panel>
          )}

          {r.coefficients.length > 0 && (
            <Panel className="p-4">
              <h2 className="mb-1 text-[14px] font-semibold">Coeficientes de la regresión logística (los 20 mayores)</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-[13px]">
                  <thead><tr><th className={th}>Variable (o categoría)</th><th className={`${th} text-right`}>Coeficiente</th><th className={th}>Efecto</th></tr></thead>
                  <tbody>{r.coefficients.map((c) => <tr key={c.feature}><td className={`${td} font-mono text-[12px]`}>{c.feature}</td><td className={`${td} text-right tabular-nums`}>{num(c.coef, '', 3)}</td><td className={td}>{c.coef > 0 ? 'Sube la probabilidad' : 'La baja'}</td></tr>)}</tbody>
                </table>
              </div>
              <How>{r.how_to_read.coef}</How>
            </Panel>
          )}

          <Panel className="p-4">
            <h2 className="mb-2 text-[14px] font-semibold">Explicaciones caso por caso (máscaras por grupo de variables)</h2>
            <Tabs tabs={CASE_TABS} value={caseTab} onChange={setCaseTab} label="Tipo de caso" />
            <ul role="tabpanel" id={`panel-${caseTab}`} aria-labelledby={`tab-${caseTab}`} className="grid gap-3 lg:grid-cols-2">
              {r.local[caseTab].map((c) => <CaseCard key={`${c.cve}-${c.snapshot}`} c={c} />)}
            </ul>
            <p className="mt-2 flex flex-wrap gap-4 text-[12px] text-muted">
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-accent" aria-hidden /> empuja hacia «entra a KEV»</span>
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-muted" aria-hidden /> empuja en contra</span>
              <span>pp = puntos porcentuales del puntaje (no es una probabilidad calibrada)</span>
            </p>
            <How>{r.how_to_read.local}</How>
          </Panel>
        </>
      )}
    </div>
  )
}
