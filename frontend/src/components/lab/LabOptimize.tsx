// Fase 7 · Optimización (Optuna UI): configuración de la búsqueda, monitoreo de pruebas en vivo y visualización de resultados.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Cell, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, ScatterChart, XAxis, YAxis, ZAxis } from 'recharts'
import { toast } from 'sonner'

import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { num } from '../Descriptive'
import { Button, EmptyState, ErrorState, Field, Input, Panel, Select, Skeleton, StatusBadge, td, th } from '../ui'
import type { Dataset } from './types'

interface Param { name: string; type: 'float_log' | 'int' | 'cat'; low?: number; high?: number; choices?: string[]; default: string | number; description: string }
interface Algorithm { key: string; label: string; space: Param[]; limits: Record<string, { low: number; high: number }> }
type Range = { low?: number; high?: number; choices?: string[] }
type Space = Record<string, Range>
interface StudyTrial { number: number; state: 'completa' | 'podada' | 'falló'; value: number | null; params: Record<string, string | number>; folds: number[]; seconds: number | null; best: number | null; default: boolean }
interface Edge { param: string; side: 'inferior' | 'superior'; value: number; low: number; high: number; suggest: { low: number; high: number } | null; at_limit: boolean }
interface Config { sampler: 'tpe' | 'random'; pruner: 'median' | 'none'; n_trials: number; timeout_minutes: number; seed: number; k_in: 3 | 4 | 5; include_defaults: boolean; drop: string[] }
export interface Study {
  id: string; dataset_id: string; algorithm: string; name: string; status: 'running' | 'done' | 'stopped' | 'failed'; config: Config
  best_params: Record<string, string | number>; best_value: number | null; seconds: number | null; error: string | null; stop_requested: boolean
  n_done: number; created_at: string | null; space?: Param[]; trials?: StudyTrial[]
  summary?: { n_trials: number; n_complete: number; n_pruned: number; n_failed: number; importance: { param: string; value: number }[]; edges: Edge[]; reading: string[]; how_to_read: Record<string, string>; best_trial?: number; best_folds?: number[] }
}
interface Form extends Config { algorithm: string; space: Space }

const STATUS: Record<Study['status'], ['ok' | 'warn' | 'danger' | 'neutral', string]> = { running: ['neutral', 'En curso'], done: ['ok', 'Terminado'], stopped: ['warn', 'Detenido'], failed: ['danger', 'Falló'] }
const SAMPLER = { tpe: 'TPE (bayesiano)', random: 'Aleatorio' }
const PRUNER = { median: 'Poda por mediana', none: 'Sin poda' }
const DEFAULT_FORM: Form = { algorithm: 'logreg', sampler: 'tpe', pruner: 'median', n_trials: 30, timeout_minutes: 30, seed: 7, k_in: 3, include_defaults: true, drop: [], space: {} }

/** Valor de hiperparámetro legible, con 2 o 3 cifras significativas y sin ceros de relleno (0,0012 · 0,35 · 4,33 · 200). */
export const pv = (v: unknown) => (typeof v !== 'number' ? String(v) : Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(Math.abs(v) < 0.1 ? 2 : 3))).replace('.', ','))
const prauc = (v: number | null | undefined) => num(v ?? null, '', 4)
/** Marcas de un eje logarítmico: 5 puntos geométricos entre los extremos (recharts solo pone potencias de 10). */
const logTicks = (p: Param) => (p.type === 'float_log' && p.low && p.high ? Array.from({ length: 5 }, (_, i) => Number(((p.low as number) * ((p.high as number) / (p.low as number)) ** (i / 4)).toPrecision(2))) : undefined)
const toSpace = (params: Param[] | undefined): Space => Object.fromEntries((params ?? []).map((p) => [p.name, p.type === 'cat' ? { choices: p.choices } : { low: p.low, high: p.high }]))

function How({ children }: { children?: string }) {
  if (!children) return null
  return <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{children}</p></details>
}

function Pills<T extends string | number>({ label, value, options, onChange }: { label: string; value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div>
      <p className="mb-1 text-[12px] font-medium text-muted">{label}</p>
      <div role="group" aria-label={label} className="flex flex-wrap gap-1">
        {options.map(([v, l]) => (
          <button key={String(v)} type="button" aria-pressed={value === v} onClick={() => onChange(v)}
            className={`h-8 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-11 ${value === v ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>{l}</button>
        ))}
      </div>
    </div>
  )
}

function SpaceEditor({ algo, space, onChange }: { algo: Algorithm; space: Space; onChange: (s: Space) => void }) {
  const set = (name: string, r: Range) => onChange({ ...space, [name]: { ...space[name], ...r } })
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-[12px] font-medium text-muted">Espacio de búsqueda</legend>
      {algo.space.map((p) => {
        const cur = space[p.name] ?? {}
        if (p.type === 'cat') {
          const chosen = cur.choices ?? p.choices ?? []
          return (
            <div key={p.name} className="rounded-lg bg-sunken p-2">
              <p className="text-[12px] font-medium" title={p.description}>{p.name}</p>
              <div className="mt-1 flex flex-wrap gap-3 text-[12px]">
                {(p.choices ?? []).map((c) => (
                  <label key={c} className="flex items-center gap-1.5">
                    <input type="checkbox" className="accent-[var(--accent)]" checked={chosen.includes(c)}
                      onChange={(e) => set(p.name, { choices: e.target.checked ? [...chosen, c] : chosen.filter((x) => x !== c) })} /> {c}
                  </label>
                ))}
              </div>
            </div>
          )
        }
        const lim = algo.limits[p.name]
        return (
          <div key={p.name} className="rounded-lg bg-sunken p-2">
            <p className="text-[12px] font-medium" title={p.description}>{p.name} <span className="font-normal text-muted">· límites {pv(lim.low)} a {pv(lim.high)}{p.type === 'float_log' ? ' · escala log' : ''}</span></p>
            <div className="mt-1 grid grid-cols-2 gap-2">
              <Input aria-label={`${p.name} mínimo`} type="number" step="any" min={lim.low} max={lim.high} className="tabular-nums" value={cur.low ?? p.low ?? ''} onChange={(e) => set(p.name, { low: Number(e.target.value) })} />
              <Input aria-label={`${p.name} máximo`} type="number" step="any" min={lim.low} max={lim.high} className="tabular-nums" value={cur.high ?? p.high ?? ''} onChange={(e) => set(p.name, { high: Number(e.target.value) })} />
            </div>
          </div>
        )
      })}
    </fieldset>
  )
}

function NewStudy({ datasetId, algos, form, setForm, onStarted }: { datasetId: string; algos: Algorithm[]; form: Form; setForm: (f: Form) => void; onStarted: (id: string) => void }) {
  const algo = algos.find((a) => a.key === form.algorithm) ?? algos[0]
  const create = useMutation({
    mutationFn: () => api.post<{ study_id: string; job_id: string }>('/ml/studies', { ...form, dataset_id: datasetId, space: { ...toSpace(algo.space), ...form.space } }),
    onSuccess: (r) => { toast.success('Estudio iniciado'); onStarted(r.study_id) },
    onError: (e) => toast.error((e as Error).message),
  })
  const toggleDrop = (g: string) => setForm({ ...form, drop: form.drop.includes(g) ? form.drop.filter((x) => x !== g) : [...form.drop, g] })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <Field label="Algoritmo">
        <Select value={form.algorithm} onChange={(e) => setForm({ ...form, algorithm: e.target.value, space: {} })}>{algos.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}</Select>
      </Field>
      <Pills label="Muestreador" value={form.sampler} onChange={(v) => setForm({ ...form, sampler: v })} options={[['tpe', SAMPLER.tpe], ['random', SAMPLER.random]]} />
      <Pills label="Poda" value={form.pruner} onChange={(v) => setForm({ ...form, pruner: v })} options={[['median', PRUNER.median], ['none', PRUNER.none]]} />
      <div className="grid grid-cols-3 gap-2">
        <Field label="Pruebas"><Input type="number" min={3} max={200} value={form.n_trials} onChange={(e) => setForm({ ...form, n_trials: Number(e.target.value) })} className="tabular-nums" /></Field>
        <Field label="Máx. minutos"><Input type="number" min={1} max={240} value={form.timeout_minutes} onChange={(e) => setForm({ ...form, timeout_minutes: Number(e.target.value) })} className="tabular-nums" /></Field>
        <Field label="Semilla"><Input type="number" min={0} value={form.seed} onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })} className="tabular-nums" /></Field>
      </div>
      <Pills label="Pliegues temporales" value={form.k_in} onChange={(v) => setForm({ ...form, k_in: v })} options={[[3, '3'], [4, '4'], [5, '5']]} />
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
        <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={form.include_defaults} onChange={(e) => setForm({ ...form, include_defaults: e.target.checked })} /> Prueba 0 = valores por defecto</label>
        <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={form.drop.includes('epss')} onChange={() => toggleDrop('epss')} /> Sin EPSS</label>
        <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={form.drop.includes('cvss')} onChange={() => toggleDrop('cvss')} /> Sin CVSS</label>
      </div>
      {algo && <SpaceEditor algo={algo} space={form.space} onChange={(space) => setForm({ ...form, space })} />}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" type="submit" disabled={create.isPending}>{create.isPending ? 'Iniciando…' : 'Iniciar estudio'}</Button>
        <Button type="button" onClick={() => setForm({ ...form, space: {} })}>Restablecer espacio</Button>
      </div>
      <p className="text-[12px] text-muted">Se busca solo con la partición de desarrollo; validación y prueba no se tocan. TPE arranca con 10 pruebas al azar.</p>
    </form>
  )
}

function History({ trials }: { trials: StudyTrial[] }) {
  const pts = trials.filter((t) => t.value !== null).map((t) => ({ x: t.number, y: t.value, best: t.best, pruned: t.state !== 'completa' }))
  return (
    <figure aria-label={`Historial de optimización: ${trials.length} pruebas`}>
      <ResponsiveContainer width="100%" height={230}>
        <ComposedChart data={pts} margin={{ top: 6, right: 14, bottom: 14, left: -4 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
          <XAxis dataKey="x" type="number" domain={[0, 'dataMax']} allowDecimals={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false}
            label={{ value: 'Prueba', position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis tickFormatter={(v: number) => num(v, '', 3)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} width={52} />
          <Scatter dataKey="y" isAnimationActive={false}>{pts.map((p) => <Cell key={p.x} fill={p.pruned ? 'var(--muted)' : 'var(--accent)'} fillOpacity={p.pruned ? 0.5 : 0.9} />)}</Scatter>
          <Line dataKey="best" type="stepAfter" stroke="var(--ink)" strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
      <figcaption className="flex flex-wrap gap-3 text-[12px] text-muted">
        <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-accent" /> completa</span>
        <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-muted" /> podada (valor parcial)</span>
        <span className="flex items-center gap-1"><span className="h-0.5 w-4 bg-ink" /> mejor hasta ese momento</span>
      </figcaption>
    </figure>
  )
}

function Slice({ trials, p }: { trials: StudyTrial[]; p: Param }) {
  const done = trials.filter((t) => t.state === 'completa' && t.value !== null)
  const cats = p.choices ?? []
  const data = done.map((t) => ({ x: p.type === 'cat' ? cats.indexOf(String(t.params[p.name])) : Number(t.params[p.name]), y: t.value }))
  return (
    <figure aria-label={`PR-AUC según ${p.name}`}>
      <ResponsiveContainer width="100%" height={220}>
        <ScatterChart margin={{ top: 6, right: 14, bottom: 14, left: -4 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
          <XAxis dataKey="x" type="number" scale={p.type === 'float_log' ? 'log' : 'auto'} domain={p.type === 'cat' ? [-0.5, cats.length - 0.5] : [p.low ?? 'auto', p.high ?? 'auto']}
            ticks={p.type === 'cat' ? cats.map((_, i) => i) : logTicks(p)} tickFormatter={(v: number) => (p.type === 'cat' ? cats[v] ?? '' : pv(v))}
            tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} label={{ value: p.name, position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis dataKey="y" type="number" domain={['auto', 'auto']} tickFormatter={(v: number) => num(v, '', 3)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} width={52} />
          <Scatter data={data} fill="var(--accent)" fillOpacity={0.8} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </figure>
  )
}

function Contour({ trials, px, py }: { trials: StudyTrial[]; px: Param; py: Param }) {
  const done = trials.filter((t) => t.state === 'completa' && t.value !== null)
  const vals = done.map((t) => t.value as number)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const data = done.map((t) => ({ x: Number(t.params[px.name]), y: Number(t.params[py.name]), v: t.value as number }))
  const axis = (p: Param) => ({ type: 'number' as const, scale: p.type === 'float_log' ? ('log' as const) : ('auto' as const), domain: [p.low ?? 'auto', p.high ?? 'auto'] as [number | string, number | string], ticks: logTicks(p), tickFormatter: (v: number) => pv(v), tick: { fill: 'var(--muted)', fontSize: 11 }, tickLine: false })
  return (
    <figure aria-label={`Mapa de ${px.name} y ${py.name}: PR-AUC de ${prauc(lo)} a ${prauc(hi)}`}>
      <ResponsiveContainer width="100%" height={240}>
        <ScatterChart margin={{ top: 6, right: 14, bottom: 14, left: -4 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
          <XAxis dataKey="x" {...axis(px)} label={{ value: px.name, position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis dataKey="y" {...axis(py)} width={56} />
          <ZAxis range={[60, 60]} />
          <Scatter data={data} isAnimationActive={false}>{data.map((d, i) => <Cell key={i} fill="var(--accent)" fillOpacity={0.12 + 0.88 * (hi > lo ? (d.v - lo) / (hi - lo) : 1)} />)}</Scatter>
        </ScatterChart>
      </ResponsiveContainer>
      <figcaption className="flex items-center gap-2 text-[12px] text-muted"><span className="tabular-nums">{prauc(lo)}</span><span className="h-2 w-24 rounded-sm bg-gradient-to-r from-sunken to-accent" aria-hidden /><span className="tabular-nums">{prauc(hi)}</span><span>PR-AUC · eje vertical: <span className="font-mono">{py.name}</span></span></figcaption>
    </figure>
  )
}

function StudyDetail({ id, onReuse }: { id: string; onReuse: (s: Study, space?: Space) => void }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['ml-study', id], queryFn: () => api.get<Study>(`/ml/studies/${id}`), refetchInterval: (query) => (query.state.data?.status === 'running' ? 1500 : false) })
  const [param, setParam] = useState<string | null>(null)
  const stop = useMutation({ mutationFn: () => api.post(`/ml/studies/${id}/stop`), onSuccess: () => { toast.success('Se detendrá al terminar la prueba en curso'); void q.refetch() }, onError: (e) => toast.error((e as Error).message) })
  const train = useMutation({
    mutationFn: (s: Study) => api.post<{ model_id: string }>('/ml/models', { dataset_id: s.dataset_id, algorithm: s.algorithm, n_trials: 15, seed: s.config.seed, drop: s.config.drop, space: toSpace(s.space), study_id: s.id }),
    onSuccess: () => { toast.success('Entrenamiento iniciado: véalo en 2 · Entrenamiento'); void qc.invalidateQueries({ queryKey: ['ml-models'] }) },
    onError: (e) => toast.error((e as Error).message),
  })
  if (q.isPending) return <Panel className="p-4"><Skeleton cols={3} rows={6} /></Panel>
  if (q.isError) return <Panel><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></Panel>
  const s = q.data
  const trials = s.trials ?? []
  const space = s.space ?? []
  const sm = s.summary && 'reading' in s.summary ? s.summary : undefined // mientras corre, el resumen es {}
  const running = s.status === 'running'
  const imp = sm?.importance ?? []
  const nums = [...imp.map((i) => i.param), ...space.map((p) => p.name)].filter((n, i, a) => a.indexOf(n) === i).map((n) => space.find((p) => p.name === n)).filter((p): p is Param => !!p && p.type !== 'cat')
  const sliceParam = space.find((p) => p.name === param) ?? space.find((p) => p.name === imp[0]?.param) ?? space[0]
  const done = trials.filter((t) => t.state === 'completa')
  const perTrial = trials.length ? trials.reduce((a, t) => a + (t.seconds ?? 0), 0) / trials.length : 0
  const eta = Math.min((s.config.n_trials - trials.length) * perTrial, Math.max(0, s.config.timeout_minutes * 60 - trials.reduce((a, t) => a + (t.seconds ?? 0), 0)))
  const best = done.length ? done.reduce((a, t) => ((t.value ?? -1) > (a.value ?? -1) ? t : a)) : null

  return (
    <div className="space-y-4">
      <Panel className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">{s.name}</h2>
            <p className="text-[12px] text-muted">{SAMPLER[s.config.sampler]} · {PRUNER[s.config.pruner]} · {s.config.k_in} pliegues temporales · semilla {s.config.seed}{s.config.drop.length ? ` · sin ${s.config.drop.join(' ni ').toUpperCase()}` : ''}</p>
          </div>
          <StatusBadge kind={STATUS[s.status][0]}>{STATUS[s.status][1]}</StatusBadge>
        </div>
        <div className="mt-3">
          <div className="h-2 rounded-full bg-sunken" role="progressbar" aria-label="Pruebas terminadas" aria-valuemin={0} aria-valuemax={s.config.n_trials} aria-valuenow={trials.length}>
            <div className="h-2 rounded-full bg-accent transition-[width] duration-300" style={{ width: `${Math.min(100, (100 * trials.length) / s.config.n_trials)}%` }} />
          </div>
          <p className="mt-1 flex flex-wrap justify-between gap-2 text-[12px] text-muted">
            <span>{trials.length} de {s.config.n_trials} pruebas · {done.length} completas{sm?.n_pruned || trials.some((t) => t.state === 'podada') ? ` · ${trials.filter((t) => t.state === 'podada').length} podadas` : ''}</span>
            <span>{running ? (trials.length ? `quedan ~${num(eta / 60, '', 1)} min` : 'primera prueba en curso…') : s.seconds !== null ? `${num(s.seconds / 60, '', 1)} min` : ''}</span>
          </p>
        </div>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-sunken p-3"><dt className="text-[12px] text-muted">Mejor PR-AUC interna</dt><dd className="mt-1 text-[20px] font-semibold tabular-nums">{prauc(s.best_value ?? best?.value)}</dd></div>
          <div className="rounded-lg bg-sunken p-3 sm:col-span-2"><dt className="text-[12px] text-muted">Mejores hiperparámetros{best ? ` (prueba ${best.number})` : ''}</dt>
            <dd className="mt-1 font-mono text-[12px]">{best ? Object.entries(best.params).map(([k, v]) => `${k}=${pv(v)}`).join(' · ') : '—'}</dd></div>
        </dl>
        {s.error && <p className="mt-2 text-[12px] text-danger">{s.error}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {running && can('ml', 'create') && <Button onClick={() => stop.mutate()} disabled={stop.isPending || s.stop_requested}>{s.stop_requested ? 'Deteniendo…' : 'Detener'}</Button>}
          {!running && can('ml', 'create') && <Button onClick={() => onReuse(s)}>Reutilizar configuración</Button>}
          {!running && can('ml', 'create') && done.length > 0 && <Button onClick={() => train.mutate(s)} disabled={train.isPending}>{train.isPending ? 'Iniciando…' : 'Entrenar con este espacio'}</Button>}
        </div>
      </Panel>

      {trials.length > 0 && (
        <Panel className="min-w-0 p-4">
          <h3 className="mb-2 text-[13px] font-semibold">Historial de optimización</h3>
          <History trials={trials} />
          <How>{sm?.how_to_read?.history}</How>
        </Panel>
      )}

      {sm && sm.reading.length > 0 && (
        <Panel className="p-4">
          <h3 className="text-[13px] font-semibold">Lectura del estudio</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-[13px]">{sm.reading.map((t) => <li key={t}>{t}</li>)}</ul>
          {sm.edges.length > 0 && (
            <div className="mt-3 space-y-2">
              {sm.edges.map((e) => (
                <div key={e.param} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-sunken px-3 py-2 text-[12px]">
                  <span><span className="font-medium">{e.param}</span> = {pv(e.value)} en el borde {e.side} de [{pv(e.low)}, {pv(e.high)}]{e.at_limit ? ' · ya es el límite admitido' : ''}</span>
                  {e.suggest && can('ml', 'create') && <Button onClick={() => onReuse(s, { [e.param]: { low: e.suggest?.low, high: e.suggest?.high } })}>Usar [{pv(e.suggest.low)}, {pv(e.suggest.high)}]</Button>}
                </div>
              ))}
              <How>{sm.how_to_read.edges}</How>
            </div>
          )}
        </Panel>
      )}

      {done.length > 1 && (
        <div className="grid gap-4 xl:grid-cols-2">
          {imp.length > 0 && (
            <Panel className="min-w-0 p-4">
              <h3 className="mb-2 text-[13px] font-semibold">Importancia de los hiperparámetros (fANOVA)</h3>
              <ul className="space-y-1.5">
                {imp.map((i) => (
                  <li key={i.param} className="grid grid-cols-[minmax(0,150px)_1fr_52px] items-center gap-2 text-[12px]">
                    <span className="truncate font-mono">{i.param}</span>
                    <span className="h-2 rounded-sm bg-sunken" role="presentation"><span className="block h-2 rounded-sm bg-accent" style={{ width: `${i.value * 100}%` }} /></span>
                    <span className="text-right tabular-nums">{num(100 * i.value, '%', 0)}</span>
                  </li>
                ))}
              </ul>
              <How>{sm?.how_to_read.importance}</How>
            </Panel>
          )}
          {sliceParam && (
            <Panel className="min-w-0 p-4">
              <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
                <h3 className="text-[13px] font-semibold">Corte por hiperparámetro</h3>
                <div className="w-48"><Select aria-label="Hiperparámetro" value={sliceParam.name} onChange={(e) => setParam(e.target.value)}>{space.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</Select></div>
              </div>
              <Slice trials={trials} p={sliceParam} />
              <How>{sm?.how_to_read?.slice}</How>
            </Panel>
          )}
          {nums.length >= 2 && (
            <Panel className="min-w-0 p-4">
              <h3 className="mb-2 text-[13px] font-semibold">Mapa de los dos más importantes</h3>
              <Contour trials={trials} px={nums[0]} py={nums[1]} />
              <How>{sm?.how_to_read?.contour}</How>
            </Panel>
          )}
        </div>
      )}

      {trials.length > 0 && (
        <Panel className="p-4">
          <h3 className="mb-2 text-[13px] font-semibold">Pruebas</h3>
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>#</th><th className={th}>Estado</th><th className={`${th} text-right`}>PR-AUC</th><th className={th}>Por pliegue</th><th className={th}>Hiperparámetros</th><th className={`${th} text-right`}>Segundos</th></tr></thead>
              <tbody>
                {[...trials].reverse().map((t) => (
                  <tr key={t.number}>
                    <td className={`${td} tabular-nums`}>{t.number}</td>
                    <td className={`${td} text-muted`}>{t.state}{t.default ? ' · por defecto' : ''}{best?.number === t.number ? ' · mejor' : ''}</td>
                    <td className={`${td} text-right tabular-nums ${best?.number === t.number ? 'font-semibold' : ''}`}>{prauc(t.value)}</td>
                    <td className={`${td} whitespace-nowrap tabular-nums text-muted`}>{t.folds.map((f) => num(f, '', 3)).join(' · ')}</td>
                    <td className={`${td} font-mono text-[12px]`}>{Object.entries(t.params).map(([k, v]) => `${k}=${pv(v)}`).join(' · ')}</td>
                    <td className={`${td} text-right tabular-nums`}>{num(t.seconds, '', 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  )
}

export function LabOptimize({ datasets }: { datasets: Dataset[] }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const ready = datasets.filter((d) => d.status === 'ready')
  const preferred = ready.find((d) => !d.tags.includes('descartado')) ?? ready[0]
  const [dsId, setDsId] = useState<string | null>(null)
  const datasetId = dsId ?? preferred?.id ?? null
  const algos = useQuery({ queryKey: ['ml-algorithms'], queryFn: () => api.get<Algorithm[]>('/ml/algorithms') })
  const studies = useQuery({ queryKey: ['ml-studies', datasetId], queryFn: () => api.get<Study[]>('/ml/studies', { dataset_id: datasetId ?? '' }), enabled: !!datasetId,
    refetchInterval: (query) => (query.state.data?.some((x) => x.status === 'running') ? 3000 : false) })
  const [picked, setPicked] = useState<string | null>(null)
  const [form, setForm] = useState<Form>(DEFAULT_FORM)
  const selected = picked ?? studies.data?.[0]?.id ?? null
  if (!ready.length) return <Panel><EmptyState title="Aún no hay datasets listos" hint="Construya uno en la fase 1 · Datos." /></Panel>
  const reuse = (s: Study, override?: Space) => {
    setForm({ ...s.config, algorithm: s.algorithm, space: { ...toSpace(s.space), ...override } })
    toast.success(override ? 'Rango sugerido cargado en «Nuevo estudio»' : 'Configuración cargada en «Nuevo estudio»')
  }

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Panel className="p-4"><Field label="Dataset"><Select value={datasetId ?? ''} onChange={(e) => { setDsId(e.target.value); setPicked(null) }}>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field></Panel>
        {can('ml', 'create') && datasetId && algos.data && (
          <Panel className="p-4">
            <h2 className="mb-2 text-[14px] font-semibold">Nuevo estudio</h2>
            <NewStudy datasetId={datasetId} algos={algos.data} form={form} setForm={setForm}
              onStarted={(id) => { setPicked(id); void qc.invalidateQueries({ queryKey: ['ml-studies', datasetId] }) }} />
          </Panel>
        )}
        <Panel className="p-2">
          <h2 className="px-2 pb-1 pt-2 text-[14px] font-semibold">Estudios</h2>
          {studies.isPending ? <Skeleton cols={1} rows={3} /> : studies.isError ? <ErrorState message={studies.error.message} onRetry={() => void studies.refetch()} /> : studies.data.length === 0 ? (
            <EmptyState compact title="Aún no hay estudios" hint="Configure la búsqueda y lance el primero." />
          ) : (
            <ul className="space-y-1">
              {studies.data.map((x) => (
                <li key={x.id}>
                  <button type="button" onClick={() => setPicked(x.id)} aria-current={selected === x.id ? 'true' : undefined}
                    className={`w-full rounded-lg px-3 py-2 text-left transition-colors duration-150 pointer-coarse:py-3 ${selected === x.id ? 'bg-sunken' : 'hover:bg-sunken'}`}>
                    <span className="flex items-center justify-between gap-2"><span className="truncate text-[13px] font-medium">{x.name}</span><StatusBadge kind={STATUS[x.status][0]}>{STATUS[x.status][1]}</StatusBadge></span>
                    <span className="text-[12px] text-muted">{x.n_done}/{x.config.n_trials} pruebas · mejor {prauc(x.best_value)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      {selected ? <StudyDetail key={selected} id={selected} onReuse={reuse} /> : (
        <Panel><EmptyState title="Elija o lance un estudio" hint="Verá cada prueba en vivo, su historial, la importancia de cada hiperparámetro y los avisos de rango." /></Panel>
      )}
    </div>
  )
}
