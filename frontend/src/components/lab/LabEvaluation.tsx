// Fase 3 · Evaluación: métricas en prueba, matrices de confusión, curvas ROC/PR, pruebas estadísticas y estabilidad.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts'

import { api } from '../../lib/api'
import { JobProgress } from './JobProgress'
import { num } from '../Descriptive'
import { EmptyState, ErrorState, Field, Panel, Select, Skeleton, td, th } from '../ui'
import type { Dataset } from './types'

interface M { rows: number; positives: number; prevalence_pct: number | null; pr_auc: number | null; roc_auc: number | null; recall_1pct: number | null; recall_5pct: number | null }
interface Row { key: string; label: string; kind: 'modelo' | 'base'; test: M; validation: M }
interface Conf { raw: { tp: number; fp: number; fn: number; tn: number }; estimated: { tp: number; fp: number; fn: number; tn: number }; recall: number; precision: number | null; effort_pct: number; threshold: number }
interface Diff { diff: number; ci: [number, number]; p: number }
interface Pair { a: string; b: string; b_label: string; pr_auc: Diff; roc_auc: Diff; mcnemar: { only_a: number; only_b: number; p: number } }
export interface EvalResult {
  operating_pct: number; rows: Row[]; best: string; test_best?: string; confusion: Record<string, Conf>
  curves: Record<string, { roc: { fpr: number; tpr: number }[]; pr: { recall: number; precision: number }[] }>
  pairs: Pair[]; friedman: { stat: number | null; p: number | null; keys: string[]; mean_rank?: Record<string, number> }
  stability: (Record<string, number | string | null> & { snapshot: string; positives: number; epss_model?: string })[]
  test_prevalence_pct: number | null; interpretation: string[]; how_to_read: Record<string, string>
  models: { id: string; name: string; algorithm: string; drop: string[] }[]
}

interface Computing { status: 'computing'; job_id: string }

const STROKES = [
  { stroke: 'var(--accent)', width: 2.5 }, { stroke: 'var(--ink)', width: 2, dash: '6 3' }, { stroke: 'var(--warn)', width: 2 },
  { stroke: 'var(--ok)', width: 2, dash: '2 3' }, { stroke: 'var(--link)', width: 2, dash: '8 2 2 2' },
]
const BASE = { epss: { stroke: 'var(--muted)', width: 1.6, dash: '4 3' }, cvss: { stroke: 'var(--line-strong)', width: 1.4, dash: '1 3' } } as const
const pct = (v: number) => `${Math.round(v * 100)} %`
const p3 = (p: number | null | undefined) => (p === null || p === undefined ? '—' : p < 0.001 ? '< 0,001' : num(p, '', 3))

function How({ children }: { children?: string }) {
  if (!children) return null
  return <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{children}</p></details>
}

function styleOf(r: Row, i: number) {
  return r.kind === 'base' ? BASE[r.key as 'epss' | 'cvss'] : STROKES[i % STROKES.length]
}

function Curves({ r }: { r: EvalResult }) {
  const models = r.rows.filter((x) => x.kind === 'modelo')
  const order = [...models, ...r.rows.filter((x) => x.kind === 'base')]
  const style = (row: Row) => styleOf(row, models.indexOf(row))
  const legend = (
    <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
      {order.map((row) => { const s = style(row); return (
        <li key={row.key} className="flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" stroke={s.stroke} strokeWidth={s.width} strokeDasharray={'dash' in s ? s.dash : undefined} /></svg>
          <span className={row.key === r.best ? 'font-medium text-ink' : ''}>{row.label}</span>
        </li>
      ) })}
    </ul>
  )
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {(['roc', 'pr'] as const).map((kind) => (
        <figure key={kind} aria-label={kind === 'roc' ? 'Curvas ROC en prueba' : 'Curvas de precisión frente a cobertura en prueba'}>
          <h3 className="mb-1 text-[13px] font-semibold">{kind === 'roc' ? 'Curva ROC (prueba)' : 'Precisión frente a cobertura (prueba)'}</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart margin={{ top: 6, right: 14, bottom: 14, left: -10 }}>
              <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
              <XAxis type="number" dataKey={kind === 'roc' ? 'fpr' : 'recall'} domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={pct} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false}
                label={{ value: kind === 'roc' ? 'CVE sin KEV arrastrados' : 'Cobertura de KEV', position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
              <YAxis type="number" domain={kind === 'roc' ? [0, 1] : [0, 'auto']} tickFormatter={kind === 'roc' ? pct : (v: number) => num(v, '', 2)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
              {kind === 'roc' && <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--line-strong)" strokeDasharray="3 3" />}
              {order.map((row) => { const s = style(row); return (
                <Line key={row.key} data={kind === 'roc' ? r.curves[row.key].roc : r.curves[row.key].pr} dataKey={kind === 'roc' ? 'tpr' : 'precision'} name={row.label}
                  type={kind === 'roc' ? 'linear' : 'stepAfter'} stroke={s.stroke} strokeWidth={s.width} strokeDasharray={'dash' in s ? s.dash : undefined} dot={false} isAnimationActive={false} />
              ) })}
            </LineChart>
          </ResponsiveContainer>
          <figcaption>{legend}</figcaption>
        </figure>
      ))}
    </div>
  )
}

function ConfusionCard({ label, c, best }: { label: string; c: Conf; best: boolean }) {
  const cell = 'px-2 py-1.5 text-right tabular-nums'
  const n = (v: number) => v.toLocaleString('es-PE').replace(/[,.]/g, ' ')
  return (
    <li className={`rounded-lg border p-3 ${best ? 'border-line-strong' : 'border-line'}`}>
      <h4 className="text-[13px] font-medium">{label}{best && <span className="ml-1 text-[12px] font-normal text-muted">(elegido en validación)</span>}</h4>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-[13px]">
        <div><dt className="text-[12px] text-muted">Cobertura</dt><dd className="font-medium tabular-nums">{num(100 * c.recall, '%', 0)}</dd></div>
        <div><dt className="text-[12px] text-muted">Precisión</dt><dd className="font-medium tabular-nums">{c.precision === null ? '—' : num(100 * c.precision, '%', 2)}</dd></div>
        <div><dt className="text-[12px] text-muted">Esfuerzo real</dt><dd className="font-medium tabular-nums">{num(c.effort_pct, '%', 2)}</dd></div>
      </dl>
      <table className="mt-2 w-full text-[12px]" aria-label={`Matriz de confusión: ${label}`}>
        <thead><tr className="text-muted"><td /><th scope="col" className="px-2 py-1 text-right font-normal">Entró a KEV</th><th scope="col" className="px-2 py-1 text-right font-normal">No entró</th></tr></thead>
        <tbody className="border-t border-line">
          <tr><th scope="row" className="py-1.5 pr-2 text-left font-normal text-muted">Marcado</th><td className={cell}>{n(c.raw.tp)}</td><td className={cell}>{n(c.raw.fp)} <span className="text-muted">(~{n(c.estimated.fp)})</span></td></tr>
          <tr className="border-t border-line"><th scope="row" className="py-1.5 pr-2 text-left font-normal text-muted">Sin marcar</th><td className={`${cell} ${c.raw.fn ? 'font-semibold' : ''}`}>{n(c.raw.fn)}</td><td className={cell}>{n(c.raw.tn)} <span className="text-muted">(~{n(c.estimated.tn)})</span></td></tr>
        </tbody>
      </table>
    </li>
  )
}

export function LabEvaluation({ datasets }: { datasets: Dataset[] }) {
  const ready = datasets.filter((d) => d.status === 'ready')
  const preferred = ready.find((d) => !d.tags.includes('descartado')) ?? ready[0]
  const [dsId, setDsId] = useState<string | null>(null)
  const [op, setOp] = useState<1 | 5>(1)
  const datasetId = dsId ?? preferred?.id ?? null
  const q = useQuery({ queryKey: ['ml-eval', datasetId, op], queryFn: () => api.get<EvalResult | Computing>(`/ml/datasets/${datasetId}/evaluation`, { op }), enabled: !!datasetId, retry: false })
  if (!ready.length) return <Panel><EmptyState title="Aún no hay datasets listos" hint="Construya uno en la fase 1 · Datos." /></Panel>
  const computing = q.data && 'status' in q.data ? q.data : null
  const r = q.data && !('status' in q.data) ? q.data : undefined
  const label = (k: string) => r?.rows.find((x) => x.key === k)?.label ?? k

  return (
    <div className="space-y-4">
      <Panel className="flex flex-wrap items-end gap-4 p-4">
        <div className="w-72"><Field label="Dataset"><Select value={datasetId ?? ''} onChange={(e) => setDsId(e.target.value)}>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field></div>
        <div>
          <p className="mb-1 text-[12px] font-medium text-muted">Punto de operación</p>
          <div role="group" aria-label="Punto de operación" className="flex gap-1">
            {([1, 5] as const).map((v) => (
              <button key={v} type="button" aria-pressed={op === v} onClick={() => setOp(v)}
                className={`h-8 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-11 ${op === v ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>Revisar el {v} %</button>
            ))}
          </div>
        </div>
        <p className="max-w-prose text-[12px] text-muted">Todo se mide en la partición de prueba (los meses más recientes, que ningún modelo vio). El umbral se fija en validación.</p>
      </Panel>

      {q.isPending ? <Panel className="p-4"><p className="mb-2 text-[13px] text-muted">Calculando la evaluación (curvas, bootstrap y pruebas): puede tardar un minuto la primera vez.</p><Skeleton cols={4} rows={6} /></Panel>
        : q.isError ? <Panel><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></Panel>
        : computing ? (
          <Panel className="p-4">
            <h2 className="mb-2 text-[14px] font-semibold">Calculando la evaluación</h2>
            <JobProgress jobId={computing.job_id} onDone={() => void q.refetch()} />
            <p className="mt-2 text-[12px] text-muted">El bootstrap pareado recalcula las métricas cientos de veces; el resultado queda guardado y la próxima vez carga al instante.</p>
          </Panel>
        ) : r && (
        <>
          <Panel className="p-4">
            <h2 className="text-[14px] font-semibold">Lectura de los resultados</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px]">{r.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>
          </Panel>

          <Panel className="p-4">
            <h2 className="mb-1 text-[14px] font-semibold">Métricas por modelo</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead><tr><th className={th}>Criterio</th><th className={`${th} text-right`}>PR-AUC prueba</th><th className={`${th} text-right`}>ROC-AUC prueba</th><th className={`${th} text-right`}>Cobertura 1 %</th><th className={`${th} text-right`}>Cobertura 5 %</th><th className={`${th} text-right`}>PR-AUC validación</th></tr></thead>
                <tbody>
                  {r.rows.map((x) => (
                    <tr key={x.key}>
                      <td className={`${td} min-w-[240px] ${x.key === r.best ? 'font-semibold' : ''}`}>
                        {x.label}{x.kind === 'base' && <span className="ml-1 text-[12px] text-muted">· línea base</span>}
                        {x.key === r.best && <span className="ml-1 text-[12px] font-normal text-muted">· elegido en validación</span>}
                        {x.key === r.test_best && x.key !== r.best && <span className="ml-1 text-[12px] font-normal text-muted">· mejor en prueba</span>}
                      </td>
                      <td className={`${td} text-right tabular-nums ${x.key === r.best ? 'font-semibold' : ''}`}>{num(x.test.pr_auc, '', 4)}</td>
                      <td className={`${td} text-right tabular-nums`}>{num(x.test.roc_auc, '', 3)}</td>
                      <td className={`${td} text-right tabular-nums`}>{x.test.recall_1pct === null ? '—' : num(100 * x.test.recall_1pct, '%', 0)}</td>
                      <td className={`${td} text-right tabular-nums`}>{x.test.recall_5pct === null ? '—' : num(100 * x.test.recall_5pct, '%', 0)}</td>
                      <td className={`${td} text-right tabular-nums text-muted`}>{num(x.validation.pr_auc, '', 4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-[12px] text-muted">Prueba: {r.rows[0].test.positives} CVE que entraron a KEV; proporción real {num(r.test_prevalence_pct, '%', 4)}.</p>
            <How>{r.how_to_read.metrics}</How>
          </Panel>

          <Panel className="p-4"><Curves r={r} /><How>{r.how_to_read.curves}</How></Panel>

          <Panel className="p-4">
            <h2 className="mb-2 text-[14px] font-semibold">Matrices de confusión (revisando el {r.operating_pct} %)</h2>
            <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{r.rows.map((x) => <ConfusionCard key={x.key} label={x.label} c={r.confusion[x.key]} best={x.key === r.best} />)}</ul>
            <How>{r.how_to_read.confusion}</How>
          </Panel>

          <Panel className="p-4">
            <h2 className="mb-2 text-[14px] font-semibold">Pruebas estadísticas</h2>
            <h3 className="text-[13px] font-semibold">Friedman (5 pliegues de la CV anidada)</h3>
            <p className="text-[13px]">χ² = {num(r.friedman.stat, '', 1)} · {r.friedman.p !== null && r.friedman.p < 0.001 ? 'p < 0,001' : `p = ${p3(r.friedman.p)}`}</p>
            {r.friedman.mean_rank && (
              <ul className="mt-1 flex flex-wrap gap-x-4 text-[12px] text-muted">
                {Object.entries(r.friedman.mean_rank).sort((a, b) => a[1] - b[1]).map(([k, v]) => <li key={k}>{label(k)}: rango medio {num(v, '', 1)}</li>)}
              </ul>
            )}
            <How>{r.how_to_read.friedman}</How>
            <h3 className="mt-4 text-[13px] font-semibold">Modelo elegido en validación ({label(r.best)}) frente a cada criterio, en prueba</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead><tr><th className={th}>Frente a</th><th className={`${th} text-right`}>Δ PR-AUC (IC 95 %)</th><th className={`${th} text-right`}>p</th><th className={`${th} text-right`}>Δ ROC-AUC (IC 95 %)</th><th className={`${th} text-right`}>p</th><th className={`${th} text-right`}>McNemar (solo elegido / solo otro)</th></tr></thead>
                <tbody>
                  {r.pairs.map((p) => (
                    <tr key={p.b}>
                      <td className={`${td} min-w-[220px]`}>{p.b_label}</td>
                      <td className={`${td} whitespace-nowrap text-right tabular-nums`}>{num(p.pr_auc.diff, '', 4)} <span className="text-muted">({num(p.pr_auc.ci[0], '', 4)} a {num(p.pr_auc.ci[1], '', 4)})</span></td>
                      <td className={`${td} whitespace-nowrap text-right tabular-nums`}>{p3(p.pr_auc.p)}</td>
                      <td className={`${td} whitespace-nowrap text-right tabular-nums`}>{num(p.roc_auc.diff, '', 3)} <span className="text-muted">({num(p.roc_auc.ci[0], '', 3)} a {num(p.roc_auc.ci[1], '', 3)})</span></td>
                      <td className={`${td} whitespace-nowrap text-right tabular-nums`}>{p3(p.roc_auc.p)}</td>
                      <td className={`${td} whitespace-nowrap text-right tabular-nums`}>{p.mcnemar.only_a} / {p.mcnemar.only_b} · p {p3(p.mcnemar.p)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <How>{`${r.how_to_read.bootstrap} ${r.how_to_read.mcnemar}`}</How>
          </Panel>

          <Panel className="p-4">
            <h2 className="mb-1 text-[14px] font-semibold">Estabilidad mes a mes (PR-AUC en prueba)</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead><tr><th className={th}>Mes</th><th className={th}>Versión EPSS</th><th className={`${th} text-right`}>KEV</th>{r.rows.map((x) => <th key={x.key} className={`${th} text-right`}>{x.label}</th>)}</tr></thead>
                <tbody>
                  {r.stability.map((s) => (
                    <tr key={s.snapshot}>
                      <td className={`${td} tabular-nums`}>{s.snapshot.slice(0, 7)}</td>
                      <td className={`${td} font-mono text-[12px]`}>{s.epss_model ?? '—'}</td>
                      <td className={`${td} text-right tabular-nums`}>{s.positives}</td>
                      {r.rows.map((x) => <td key={x.key} className={`${td} text-right tabular-nums ${x.key === r.best ? 'font-medium' : ''}`}>{num(s[x.key] as number | null, '', 4)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <How>{r.how_to_read.stability}</How>
          </Panel>
        </>
      )}
    </div>
  )
}
