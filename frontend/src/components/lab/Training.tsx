// Fase 2 · Entrenamiento: selector de modelo, hiperparámetros, CV anidada temporal 5×3 con Optuna y monitoreo en vivo.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, XAxis, YAxis, ZAxis } from 'recharts'
import { toast } from 'sonner'

import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { formatDate, formatLima } from '../../lib/format'
import { JobProgress } from './JobProgress'
import { num } from '../Descriptive'
import { Button, EmptyState, ErrorState, Field, Input, Panel, Select, Skeleton, StatusBadge, td, th } from '../ui'
import type { Dataset } from './types'

interface Param { name: string; type: 'float_log' | 'int' | 'cat'; low?: number; high?: number; choices?: string[]; default: string | number; description: string }
interface Algorithm { key: string; label: string; family: string; description: string; space: Param[]; defaults: Record<string, unknown> }
interface Metrics { rows: number; positives: number; prevalence_pct: number | null; pr_auc: number | null; roc_auc: number | null; recall_1pct: number | null; recall_5pct: number | null }
interface Fold { fold: number; train: [string, string]; val: [string, string]; train_rows: number; train_positives: number; best_params: Record<string, unknown>; metrics: Metrics; baselines: Record<string, Metrics> }
interface Stat { mean: number | null; sd: number | null; n: number }
interface Trial { fold: string; trial: number; value: number; params: Record<string, unknown>; seconds: number }
export interface Model {
  id: string; dataset_id: string; algorithm: string; name: string; status: 'training' | 'ready' | 'failed'
  config: { n_trials: number; k_out: number; k_in: number; seed: number; metric: string; cv: string; target: string }
  aggregate: { model?: Record<string, Stat>; epss?: Record<string, Stat>; cvss?: Record<string, Stat>; wins_vs_epss?: number }
  best_params: Record<string, unknown>; final_metrics: Record<string, Metrics>; reading: string[]; seconds: number | null; error: string | null
  created_at: string | null; finished_at: string | null; folds?: Fold[]; trials?: Trial[]
}

const STATUS: Record<Model['status'], ['ok' | 'neutral' | 'danger', string]> = { ready: ['ok', 'Listo'], training: ['neutral', 'Entrenando'], failed: ['danger', 'Falló'] }
const TRIALS = [5, 15, 30] as const
const FOLD_COLORS = ['var(--accent)', 'var(--ink)', 'var(--muted)', 'var(--warn)', 'var(--ok)', 'var(--link)']

function range(p: Param): string {
  if (p.type === 'cat') return (p.choices ?? []).join(' · ')
  const f = (v?: number) => (v === undefined ? '—' : v < 0.01 ? String(v).replace('.', ',') : num(v, '', v < 1 ? 2 : 0))
  return `${f(p.low)} a ${f(p.high)}${p.type === 'float_log' ? ' (escala log)' : ''}`
}
const fmtParams = (p: Record<string, unknown>) => Object.entries(p).map(([k, v]) => `${k}=${typeof v === 'number' ? (Number.isInteger(v) ? v : num(v, '', 3)) : String(v)}`).join(' · ')

/** Pruebas de Optuna (PR-AUC interna) a medida que llegan; un color por pliegue externo. */
function TrialsChart({ trials }: { trials: Trial[] }) {
  const tags = [...new Set(trials.map((t) => t.fold))]
  const data = trials.map((t, i) => ({ i: i + 1, v: t.value, tag: t.fold }))
  return (
    <figure aria-label={`${trials.length} pruebas de Optuna; la mejor PR-AUC interna es ${num(Math.max(0, ...trials.map((t) => t.value)), '', 4)}`}>
      <ResponsiveContainer width="100%" height={200}>
        <ScatterChart margin={{ top: 8, right: 16, bottom: 14, left: -8 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
          <XAxis type="number" dataKey="i" name="Prueba" allowDecimals={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false}
            label={{ value: 'Prueba (en orden)', position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis type="number" dataKey="v" name="PR-AUC" tickFormatter={(v: number) => num(v, '', 3)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
          <ZAxis range={[30, 30]} />
          {tags.map((t, k) => <Scatter key={t} data={data.filter((d) => d.tag === t)} fill={FOLD_COLORS[k % FOLD_COLORS.length]} isAnimationActive={false} name={t} />)}
        </ScatterChart>
      </ResponsiveContainer>
      <figcaption className="flex flex-wrap gap-3 text-[12px] text-muted">
        {tags.map((t, k) => <span key={t} className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ background: FOLD_COLORS[k % FOLD_COLORS.length] }} aria-hidden />{t}</span>)}
      </figcaption>
    </figure>
  )
}

function FoldsTable({ folds }: { folds: Fold[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr>
            <th className={th}>Pliegue</th><th className={th}>Entrena (fotos)</th><th className={th}>Valida (outer_val)</th><th className={`${th} text-right`}>KEV en val.</th>
            <th className={`${th} text-right`}>PR-AUC</th><th className={`${th} text-right`}>ROC-AUC</th><th className={`${th} text-right`}>Cobertura 1 %</th><th className={`${th} text-right`}>PR-AUC EPSS</th>
          </tr>
        </thead>
        <tbody>
          {folds.map((f) => (
            <tr key={f.fold} title={`Mejores hiperparámetros: ${fmtParams(f.best_params)}`}>
              <td className={td}>{f.fold}</td>
              <td className={`${td} whitespace-nowrap tabular-nums`}>{f.train[0].slice(0, 7)} a {f.train[1].slice(0, 7)}</td>
              <td className={`${td} whitespace-nowrap tabular-nums`}>{f.val[0].slice(0, 7)} a {f.val[1].slice(0, 7)}</td>
              <td className={`${td} text-right tabular-nums`}>{f.metrics.positives}</td>
              <td className={`${td} text-right font-medium tabular-nums`}>{num(f.metrics.pr_auc, '', 4)}</td>
              <td className={`${td} text-right tabular-nums`}>{num(f.metrics.roc_auc, '', 3)}</td>
              <td className={`${td} text-right tabular-nums`}>{f.metrics.recall_1pct === null ? '—' : num(100 * f.metrics.recall_1pct, '%', 0)}</td>
              <td className={`${td} text-right tabular-nums`}>{num(f.baselines.epss?.pr_auc, '', 4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ModelDetail({ id }: { id: string }) {
  const q = useQuery({
    queryKey: ['ml-model', id],
    queryFn: () => api.get<Model>(`/ml/models/${id}`),
    refetchInterval: (query) => (query.state.data?.status === 'training' ? 2000 : false),
  })
  if (q.isPending) return <Skeleton cols={3} rows={5} />
  if (q.isError) return <ErrorState message={q.error.message} onRetry={() => void q.refetch()} />
  const m = q.data
  const agg = m.aggregate
  const rows: [string, Record<string, Stat> | undefined][] = [['Modelo entrenado', agg.model], ['EPSS (sin entrenar)', agg.epss], ['CVSS de la CNA (sin entrenar)', agg.cvss]]
  return (
    <div className="space-y-5">
      <p className="text-[12px] text-muted">
        Clase objetivo: {m.config.target} · CV {m.config.cv}, {m.config.k_out} pliegues externos × {m.config.k_in} internos · {m.config.n_trials} pruebas de Optuna por búsqueda ·
        métrica {m.config.metric} · semilla {m.config.seed}{m.seconds ? ` · ${num(m.seconds / 60, '', 1)} min` : ''}
      </p>
      {m.status === 'failed' && <p className="text-[13px]">El entrenamiento falló: {m.error}</p>}
      {m.reading.length > 0 && <ul className="list-disc space-y-1 pl-5 text-[13px]">{m.reading.map((t) => <li key={t}>{t}</li>)}</ul>}
      {(m.trials?.length ?? 0) > 0 && (
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Pruebas de Optuna {m.status === 'training' && <span className="font-normal text-muted">(en vivo)</span>}</h3>
          <TrialsChart trials={m.trials ?? []} />
        </div>
      )}
      {(m.folds?.length ?? 0) > 0 && (
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Resultado por pliegue externo (una evaluación por pliegue)</h3>
          <FoldsTable folds={m.folds ?? []} />
          <p className="mt-1 text-[12px] text-muted">Pase el cursor sobre una fila para ver sus mejores hiperparámetros. Cada pliegue entrena con el pasado y valida con los meses siguientes.</p>
        </div>
      )}
      {agg.model && (
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Agregado de los {m.config.k_out} pliegues (media ± desviación)</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>Criterio</th><th className={`${th} text-right`}>PR-AUC</th><th className={`${th} text-right`}>ROC-AUC</th><th className={`${th} text-right`}>Cobertura 1 %</th><th className={`${th} text-right`}>Cobertura 5 %</th></tr></thead>
              <tbody>
                {rows.map(([label, s]) => s && (
                  <tr key={label}>
                    <td className={`${td} ${label.startsWith('Modelo') ? 'font-medium' : ''}`}>{label}</td>
                    {(['pr_auc', 'roc_auc', 'recall_1pct', 'recall_5pct'] as const).map((k) => (
                      <td key={k} className={`${td} text-right tabular-nums`}>
                        {k.startsWith('recall') ? (s[k].mean === null ? '—' : `${num(100 * s[k].mean, '%', 0)} ± ${num(100 * (s[k].sd ?? 0), '', 0)}`) : `${num(s[k].mean, '', 4)} ± ${num(s[k].sd, '', 4)}`}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {Object.keys(m.best_params).length > 0 && (
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Modelo final (búsqueda en todo desarrollo)</h3>
          <p className="text-[13px]"><span className="text-muted">Hiperparámetros elegidos:</span> <span className="break-words font-mono text-[12px]">{fmtParams(m.best_params)}</span></p>
          {m.final_metrics.validacion && (
            <p className="text-[13px]"><span className="text-muted">Validación (15 %):</span> PR-AUC {num(m.final_metrics.validacion.pr_auc, '', 4)} · ROC-AUC {num(m.final_metrics.validacion.roc_auc, '', 3)} · {m.final_metrics.validacion.positives} CVE que entraron a KEV. La prueba (15 %) queda para la Fase 3.</p>
          )}
        </div>
      )}
    </div>
  )
}

export function Training({ datasets }: { datasets: Dataset[] }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const ready = datasets.filter((d) => d.status === 'ready')
  const preferred = ready.find((d) => !d.tags.includes('descartado')) ?? ready[0]
  const [dsId, setDsId] = useState<string | null>(null)
  const datasetId = dsId ?? preferred?.id ?? null
  const ds = ready.find((d) => d.id === datasetId)
  const algos = useQuery({ queryKey: ['ml-algorithms'], queryFn: () => api.get<Algorithm[]>('/ml/algorithms') })
  const models = useQuery({ queryKey: ['ml-models', datasetId], queryFn: () => api.get<Model[]>('/ml/models', { dataset_id: datasetId ?? '' }), enabled: !!datasetId,
    refetchInterval: (query) => (query.state.data?.some((x) => x.status === 'training') ? 3000 : false) })
  const [algo, setAlgo] = useState('hgb')
  const [nTrials, setNTrials] = useState<(typeof TRIALS)[number]>(15)
  const [seed, setSeed] = useState(7)
  const [picked, setPicked] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const selected = picked ?? models.data?.[0]?.id ?? null
  const train = useMutation({
    mutationFn: () => api.post<{ model_id: string; job_id: string }>('/ml/models', { dataset_id: datasetId, algorithm: algo, n_trials: nTrials, seed }),
    onSuccess: (r) => { toast.success('Entrenamiento iniciado'); setJobId(r.job_id); setPicked(r.model_id); void qc.invalidateQueries({ queryKey: ['ml-models', datasetId] }) },
    onError: (e) => toast.error((e as Error).message),
  })
  if (!ready.length) return <Panel><EmptyState title="Aún no hay datasets listos" hint="Construya uno en la fase 1 · Datos." /></Panel>
  const current = algos.data?.find((a) => a.key === algo)
  const split = ds?.stats.by_split

  return (
    <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[420px_minmax(0,1fr)]">
      <div className="min-w-0 space-y-4">
        <Panel className="p-4">
          <h2 className="mb-2 text-[14px] font-semibold">Configurar entrenamiento</h2>
          <div className="space-y-3">
            <Field label="Dataset">
              <Select value={datasetId ?? ''} onChange={(e) => { setDsId(e.target.value); setPicked(null) }}>
                {ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
            </Field>
            {split && (
              <p className="text-[12px] text-muted">
                Clase: entra a KEV en {ds?.params.horizon_days} días (1) o no (0) · Desarrollo {split.desarrollo?.snapshots} fotos ({split.desarrollo?.positives} KEV) ·
                Validación {split.validacion?.snapshots} ({split.validacion?.positives}) · Prueba {split.prueba?.snapshots} ({split.prueba?.positives}).
              </p>
            )}
            <fieldset>
              <legend className="mb-1 text-[12px] font-medium text-muted">Modelo</legend>
              {algos.isPending ? <Skeleton cols={1} rows={3} /> : (
                <div className="space-y-1">
                  {algos.data?.map((a) => (
                    <label key={a.key} className={`flex cursor-pointer gap-2 rounded-lg px-3 py-2 transition-colors duration-150 ${algo === a.key ? 'bg-sunken' : 'hover:bg-sunken'}`}>
                      <input type="radio" name="algo" className="mt-1 accent-[var(--accent)]" checked={algo === a.key} onChange={() => setAlgo(a.key)} />
                      <span><span className="block text-[13px] font-medium">{a.label} <span className="font-normal text-muted">· {a.family}</span></span><span className="block text-[12px] text-muted">{a.description}</span></span>
                    </label>
                  ))}
                </div>
              )}
            </fieldset>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <p className="mb-1 text-[12px] font-medium text-muted">Pruebas de Optuna por búsqueda</p>
                <div role="group" aria-label="Pruebas de Optuna" className="flex gap-1">
                  {TRIALS.map((n) => (
                    <button key={n} type="button" aria-pressed={nTrials === n} onClick={() => setNTrials(n)}
                      className={`h-8 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-11 ${nTrials === n ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>{n}</button>
                  ))}
                </div>
              </div>
              <div className="w-24"><Field label="Semilla"><Input type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="tabular-nums" /></Field></div>
            </div>
            <p className="text-[12px] text-muted">CV anidada temporal: 5 pliegues externos × 3 internos; en cada externo, Optuna busca en los internos, se reentrena con los mejores y se evalúa una vez. Son {6 * nTrials} búsquedas en total.</p>
            {can('ml', 'create') && <Button variant="primary" disabled={train.isPending || !!jobId} onClick={() => train.mutate()}>{train.isPending ? 'Iniciando…' : 'Entrenar'}</Button>}
            {jobId && <JobProgress jobId={jobId} onDone={(j) => { if (j.status === 'done') toast.success('Modelo entrenado'); void qc.invalidateQueries({ queryKey: ['ml-models', datasetId] }); window.setTimeout(() => setJobId(null), 3000) }} />}
          </div>
        </Panel>
        {current && (
          <Panel className="p-4">
            <h2 className="mb-1 text-[14px] font-semibold">Hiperparámetros de {current.label}</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead><tr><th className={th}>Parámetro</th><th className={th}>Por defecto</th><th className={th}>Rango de búsqueda</th></tr></thead>
                <tbody>
                  {current.space.map((p) => (
                    <tr key={p.name} title={p.description}>
                      <td className={`${td} font-mono`}>{p.name}</td>
                      <td className={`${td} tabular-nums`}>{typeof p.default === 'number' ? String(p.default).replace('.', ',') : p.default}</td>
                      <td className={`${td} tabular-nums`}>{range(p)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="mt-2 space-y-1 text-[12px] text-muted">{current.space.map((p) => <li key={p.name}><span className="font-mono text-ink">{p.name}</span>: {p.description}</li>)}</ul>
          </Panel>
        )}
      </div>

      <Panel className="min-w-0 p-4">
        <h2 className="mb-2 text-[14px] font-semibold">Modelos de este dataset</h2>
        {models.isPending ? <Skeleton cols={4} rows={3} /> : !models.data?.length ? (
          <EmptyState compact title="Aún no hay modelos" hint="Configure y entrene el primero." />
        ) : (
          <>
            <ul className="mb-4 space-y-1">
              {models.data.map((x) => (
                <li key={x.id}>
                  <button type="button" onClick={() => setPicked(x.id)} aria-current={selected === x.id ? 'true' : undefined}
                    className={`grid w-full grid-cols-[1fr_auto] items-center gap-2 rounded-lg px-3 py-2 text-left transition-colors duration-150 ${selected === x.id ? 'bg-sunken' : 'hover:bg-sunken'}`}>
                    <span>
                      <span className="block text-[13px] font-medium">{x.name}</span>
                      <span className="block text-[12px] text-muted tabular-nums">
                        {x.aggregate.model ? `PR-AUC ${num(x.aggregate.model.pr_auc.mean, '', 4)} ± ${num(x.aggregate.model.pr_auc.sd, '', 4)} · EPSS ${num(x.aggregate.epss?.pr_auc.mean, '', 4)} · ` : ''}
                        {x.created_at ? formatLima(x.created_at) : ''}
                      </span>
                    </span>
                    <StatusBadge kind={STATUS[x.status][0]}>{STATUS[x.status][1]}</StatusBadge>
                  </button>
                </li>
              ))}
            </ul>
            {selected && <ModelDetail key={selected} id={selected} />}
          </>
        )}
        {ds && <p className="mt-3 text-[12px] text-muted">Dataset con fotos desde {formatDate(ds.params.start)}; KEV hasta {formatDate(ds.params.until)}.</p>}
      </Panel>
    </div>
  )
}
