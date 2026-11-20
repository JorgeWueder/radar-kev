// Fase 6 · Inferencia: predicción individual con probabilidad calibrada, severidad y explicación por oclusión.
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { api } from '../../lib/api'
import { num } from '../Descriptive'
import { Tabs } from '../kit'
import { Button, EmptyState, ErrorState, Field, Input, Panel, Select, Skeleton, StatusBadge, td, th } from '../ui'
import type { Model } from './Training'
import type { Dataset } from './types'

type BandKey = 'critica' | 'alta' | 'media' | 'baja'
type Values = Record<string, string | number | null>
interface BandStat { key: BandKey; label: string; meaning: string; share: number; rows: number; positives: number; rate: number; rate_lo: number; rate_hi: number; pred: number | null; lift: number | null; recall: number }
interface Reliability { top: number; rows: number; positives: number; expected: number; pred: number; obs: number; obs_lo: number; obs_hi: number }
export interface Setup {
  model: { id: string; name: string; algorithm: string }; dataset: { id: string; name: string }; horizon_days: number; drop: string[]
  calibration: {
    params: [number, number]; thresholds: Record<string, number>; base_rate: { validacion: number; prueba: number }
    test: { observed: number; expected: number; oe: number | null; oe_lo: number | null; oe_hi: number | null; slope: number; slope_lo: number; slope_hi: number
      brier_raw: number; brier_cal: number; brier_ref: number; brier_skill: number | null; hl: number; hl_df: number; hl_p: number; positives: number; rows: number }
    bands: BandStat[]; reliability: Reliability[]; reading: string[]
  }
  baseline: Values; options: { categorical: Record<string, string[]>; numeric: Record<string, { p01: number; p99: number }> }
  features: { name: string; type: 'num' | 'cat'; source: string; description: string }[]; how_to_read: Record<string, string>
}
interface Attribution { group: string; factor: number | null; delta_score: number; band_without: BandKey; unused: boolean }
export interface Prediction {
  result: { score: number; probability: number; p_lo: number; p_hi: number; band: BandKey; top: number; lift: number | null; base_rate: number; attributions: Attribution[] }
  case: { cve: string; snapshot: string; split: string; label: number; kev_date: string | null; days_to_kev: number | null } | null
  values: Values; reading: string[]
}
interface CaseRow { cve: string; snapshot: string; split: string; label: number }
interface Ranking { snapshot: string; snapshots: string[]; split: string; hits: number; positives: number; rows: { cve: string; score: number; probability: number; band: BandKey; label: number }[] }

const BAND: Record<BandKey, ['danger' | 'warn' | 'neutral', string]> = { critica: ['danger', 'Crítica'], alta: ['warn', 'Alta'], media: ['neutral', 'Media'], baja: ['neutral', 'Baja'] }
const SPLIT: Record<string, string> = { desarrollo: 'desarrollo', validacion: 'validación', prueba: 'prueba' }
const LABEL: Record<string, string> = {
  epss: 'EPSS (0 a 1)', percentile: 'Percentil EPSS (0 a 1)', epss_delta: 'Cambio de EPSS (30 días)', epss_model: 'Versión de EPSS', cvss: 'CVSS de la CNA',
  av: 'Vector de ataque', ac: 'Complejidad', pr: 'Privilegios', ui: 'Interacción del usuario', cwe: 'CWE', cna: 'CNA',
  days_published: 'Días desde la publicación', edb_exploits: 'Exploits públicos (Exploit-DB)', cna_kev_prior: 'KEV previos de la CNA',
}
const NUMS = ['epss', 'percentile', 'epss_delta', 'cvss', 'days_published', 'edb_exploits', 'cna_kev_prior']
const CATS = ['epss_model', 'av', 'ac', 'pr', 'ui', 'cwe', 'cna']
const LIMITS: Record<string, [number, number]> = { epss: [0, 1], percentile: [0, 1], epss_delta: [-1, 1], cvss: [0, 10], days_published: [0, 20000], edb_exploits: [0, 1000], cna_kev_prior: [0, 10000] }

/** Porcentaje con decimales según la magnitud (12,3 %, 0,45 %, 0,012 %). */
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : num(100 * v, '%', 100 * v >= 1 ? 1 : 100 * v >= 0.1 ? 2 : 3))
/** Factores y «veces»: sin decimales desde 10 (×3637), uno desde 1 (×3,2) y dos por debajo (×0,45). */
const times = (f: number) => num(f, '', f >= 10 ? 0 : f >= 1 ? 1 : 2)
const factor = (f: number | null) => (f === null ? '—' : `×${times(f)}`)
const topText = (t: number) => (t <= 1e-5 ? '< 0,001 %' : pct(t))

function How({ children }: { children?: string }) {
  if (!children) return null
  return <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{children}</p></details>
}

function Badge({ band }: { band: BandKey }) {
  return <StatusBadge kind={BAND[band][0]}>{BAND[band][1]}</StatusBadge>
}

function Attributions({ rows }: { rows: Attribution[] }) {
  const mag = (a: Attribution) => (a.factor ? Math.abs(Math.log(a.factor)) : 0)
  const max = Math.max(1e-9, ...rows.map(mag))
  return (
    <ul className="space-y-1.5" aria-label="Explicación por grupo de variables">
      {rows.map((a) => (
        <li key={a.group} className={`grid grid-cols-[minmax(0,170px)_1fr_1fr_64px_74px] items-center gap-1 text-[12px] ${a.unused ? 'text-muted' : ''}`}>
          <span className="truncate" title={a.group}>{a.group}</span>
          <span className="flex justify-end">{a.factor !== null && a.factor < 1 && <span className="h-2 rounded-sm bg-muted" style={{ width: `${(mag(a) / max) * 100}%` }} />}</span>
          <span>{a.factor !== null && a.factor > 1 && <span className="block h-2 rounded-sm bg-accent" style={{ width: `${(mag(a) / max) * 100}%` }} />}</span>
          <span className="text-right font-medium tabular-nums">{a.unused ? 'no usa' : factor(a.factor)}</span>
          <span className="text-right text-muted">sin él: {BAND[a.band_without][1]}</span>
        </li>
      ))}
    </ul>
  )
}

function Result({ p, horizon, onScenario, how }: { p: Prediction; horizon: number; onScenario: () => void; how: Record<string, string> }) {
  const r = p.result
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[12px] text-muted">{p.case ? <><span className="font-mono text-ink">{p.case.cve}</span> · foto {p.case.snapshot.slice(0, 7)} · {SPLIT[p.case.split] ?? p.case.split}</> : 'Escenario con valores a mano'}</p>
          <p className="mt-1 text-[32px] font-semibold leading-none tabular-nums" aria-label={`Probabilidad calibrada ${pct(r.probability)}`}>{pct(r.probability)}</p>
          <p className="mt-1 text-[12px] text-muted">de entrar a KEV en {horizon} días · IC 90 % {pct(r.p_lo)} a {pct(r.p_hi)}</p>
        </div>
        <div className="text-right">
          <Badge band={r.band} />
          <p className="mt-1 text-[12px] text-muted">{topText(r.top)} superior del universo · {r.lift === null ? '—' : times(r.lift)} veces la tasa base</p>
          {p.case && <p className="text-[12px] text-muted">Resultado real: {p.case.label ? `entró a KEV el ${p.case.kev_date}` : 'no entró'}</p>}
        </div>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-[13px]">{p.reading.map((t) => <li key={t}>{t}</li>)}</ul>
      <How>{how.probability}</How>
      <div>
        <h3 className="mb-2 text-[13px] font-semibold">Qué la explica (oclusión por grupo)</h3>
        <Attributions rows={r.attributions} />
        <How>{how.attribution}</How>
      </div>
      {p.case && <Button onClick={onScenario}>Usar estos valores como escenario</Button>}
    </div>
  )
}

function ManualForm({ setup, values, onChange, onSubmit, busy }: { setup: Setup; values: Values; onChange: (v: Values) => void; onSubmit: () => void; busy: boolean }) {
  const set = (k: string, v: string | number | null) => onChange({ ...values, [k]: v })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
      <div className="grid gap-3 sm:grid-cols-2">
        {NUMS.map((k) => (
          <Field key={k} label={LABEL[k]}>
            <Input type="number" step="any" min={LIMITS[k][0]} max={LIMITS[k][1]} className="tabular-nums" placeholder="vacío = sin dato"
              value={values[k] === null || values[k] === undefined ? '' : String(values[k])} onChange={(e) => set(k, e.target.value === '' ? null : Number(e.target.value))} />
          </Field>
        ))}
        {CATS.map((k) => {
          const opts = setup.options.categorical[k] ?? []
          const cur = String(values[k] ?? 'desconocido')
          return (
            <Field key={k} label={LABEL[k]}>
              <Select value={cur} onChange={(e) => set(k, e.target.value)}>
                {[...new Set([cur, ...opts, 'desconocido'])].map((o) => <option key={o} value={o}>{o}</option>)}
              </Select>
            </Field>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" type="submit" disabled={busy}>{busy ? 'Calculando…' : 'Predecir'}</Button>
        <Button type="button" onClick={() => onChange({ ...setup.baseline })}>Restablecer valores típicos</Button>
      </div>
      <p className="text-[12px] text-muted">Valores típicos = mediana o categoría más común de desarrollo. Las categorías poco frecuentes se agrupan como en el entrenamiento.</p>
    </form>
  )
}

function Calibration({ setup }: { setup: Setup }) {
  const c = setup.calibration
  const t = c.test
  const kpis: [string, string, string][] = [
    ['Observado / esperado', num(t.oe, '', 2), `IC 95 % ${num(t.oe_lo, '', 2)} a ${num(t.oe_hi, '', 2)} · ideal 1`],
    ['Pendiente de calibración', num(t.slope, '', 2), `IC 95 % ${num(t.slope_lo, '', 2)} a ${num(t.slope_hi, '', 2)} · ideal 1`],
    ['Mejora del Brier', t.brier_skill === null ? '—' : num(100 * t.brier_skill, '%', 1), 'frente a predecir la tasa base'],
    ['Hosmer-Lemeshow', t.hl_p < 0.001 ? 'p < 0,001' : `p = ${num(t.hl_p, '', 3)}`, `χ² ${num(t.hl, '', 1)} con ${t.hl_df} g.l.`],
  ]
  return (
    <Panel className="p-4">
      <h2 className="text-[14px] font-semibold">Calibración y severidad</h2>
      <p className="mb-3 text-[12px] text-muted">Platt en validación; se verifica en prueba ({t.positives} entradas a KEV en {t.rows.toLocaleString('es-PE').replace(/[,.]/g, ' ')} filas). Tasa base: {pct(c.base_rate.validacion)} en validación, {pct(c.base_rate.prueba)} en prueba.</p>
      <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map(([k, v, h]) => (
          <div key={k} className="rounded-lg bg-sunken p-3">
            <dt className="text-[12px] text-muted">{k}</dt>
            <dd className="mt-1 text-[20px] font-semibold tabular-nums">{v}</dd>
            <dd className="text-[12px] text-muted">{h}</dd>
          </div>
        ))}
      </dl>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px]">{c.reading.map((r) => <li key={r}>{r}</li>)}</ul>
      <How>{setup.how_to_read.calibration}</How>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="min-w-0">
          <h3 className="mb-1 text-[13px] font-semibold">Bandas de severidad en prueba</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>Banda</th><th className={`${th} text-right`}>Universo</th><th className={`${th} text-right`}>Entraron</th><th className={`${th} text-right`}>Tasa real (IC 95 %)</th><th className={`${th} text-right`}>Predicha</th><th className={`${th} text-right`}>× tasa base</th></tr></thead>
              <tbody>
                {c.bands.map((b) => (
                  <tr key={b.key} title={b.meaning}>
                    <td className={td}><Badge band={b.key} /></td>
                    <td className={`${td} text-right tabular-nums`}>{pct(b.share)}</td>
                    <td className={`${td} text-right tabular-nums`}>{b.positives} <span className="text-muted">({num(100 * b.recall, '%', 0)})</span></td>
                    <td className={`${td} whitespace-nowrap text-right tabular-nums`}>{pct(b.rate)} <span className="text-muted">({pct(b.rate_lo)} a {pct(b.rate_hi)})</span></td>
                    <td className={`${td} text-right tabular-nums`}>{pct(b.pred)}</td>
                    <td className={`${td} text-right tabular-nums`}>{b.lift === null ? '—' : times(b.lift)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <How>{setup.how_to_read.band}</How>
        </div>
        <div className="min-w-0">
          <h3 className="mb-1 text-[13px] font-semibold">Fiabilidad por tramo (prueba)</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>Tramo superior hasta</th><th className={`${th} text-right`}>Entraron</th><th className={`${th} text-right`}>Predicha</th><th className={`${th} text-right`}>Observada (IC 95 %)</th></tr></thead>
              <tbody>
                {c.reliability.map((r) => (
                  <tr key={r.top}>
                    <td className={`${td} tabular-nums`}>{pct(r.top)}</td>
                    <td className={`${td} text-right tabular-nums`}>{r.positives}</td>
                    <td className={`${td} text-right tabular-nums`}>{pct(r.pred)}</td>
                    <td className={`${td} whitespace-nowrap text-right tabular-nums`}>{pct(r.obs)} <span className="text-muted">({pct(r.obs_lo)} a {pct(r.obs_hi)})</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <How>{setup.how_to_read.reliability}</How>
        </div>
      </div>
    </Panel>
  )
}

export function LabInference({ datasets }: { datasets: Dataset[] }) {
  const ready = datasets.filter((d) => d.status === 'ready')
  const preferred = ready.find((d) => !d.tags.includes('descartado')) ?? ready[0]
  const [dsId, setDsId] = useState<string | null>(null)
  const datasetId = dsId ?? preferred?.id ?? null
  const models = useQuery({ queryKey: ['ml-models', datasetId], queryFn: () => api.get<Model[]>('/ml/models', { dataset_id: datasetId ?? '' }), enabled: !!datasetId })
  const readyModels = (models.data ?? []).filter((m) => m.status === 'ready')
  const [picked, setPicked] = useState<string | null>(null)
  const modelId = picked ?? readyModels[0]?.id ?? null
  const setup = useQuery({ queryKey: ['ml-inference', modelId], queryFn: () => api.get<Setup>(`/ml/models/${modelId}/inference`), enabled: !!modelId, retry: false, staleTime: Infinity })
  const [shot, setShot] = useState<string | null>(null)
  const ranking = useQuery({ queryKey: ['ml-ranking', modelId, shot], queryFn: () => api.get<Ranking>(`/ml/models/${modelId}/ranking`, shot ? { snapshot: shot } : {}), enabled: !!modelId && setup.isSuccess })
  const [mode, setMode] = useState<'cve' | 'manual'>('cve')
  const [q, setQ] = useState('CVE-2026-')
  const [cases, setCases] = useState<CaseRow[] | null>(null)
  const [values, setValues] = useState<Values | null>(null)
  const [pred, setPred] = useState<Prediction | null>(null)
  const search = useMutation({
    mutationFn: () => api.get<CaseRow[]>(`/ml/models/${modelId}/cases`, { q: q.trim().toUpperCase() }),
    onSuccess: setCases, onError: (e) => toast.error((e as Error).message),
  })
  const predict = useMutation({
    mutationFn: (body: { cve: string; snapshot?: string } | { values: Values }) => api.post<Prediction>(`/ml/models/${modelId}/predict`, body),
    onSuccess: setPred, onError: (e) => toast.error((e as Error).message),
  })
  if (!ready.length) return <Panel><EmptyState title="Aún no hay datasets listos" hint="Construya uno en la fase 1 · Datos." /></Panel>
  const s = setup.data
  const form = values ?? s?.baseline ?? {}
  const reset = () => { setPred(null); setCases(null); setValues(null); setShot(null) }

  return (
    <div className="space-y-4">
      <Panel className="flex flex-wrap items-end gap-4 p-4">
        <div className="w-64"><Field label="Dataset"><Select value={datasetId ?? ''} onChange={(e) => { setDsId(e.target.value); setPicked(null); reset() }}>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field></div>
        <div className="w-80"><Field label="Modelo"><Select value={modelId ?? ''} onChange={(e) => { setPicked(e.target.value); reset() }} disabled={!readyModels.length}>{readyModels.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field></div>
        <p className="max-w-prose text-[12px] text-muted">Experimental: la predicción no cambia la detección ni el score del radar. La primera vez se calibra el modelo (unos segundos).</p>
      </Panel>

      {!readyModels.length && !models.isPending ? <Panel><EmptyState title="Aún no hay modelos entrenados" hint="Entrene uno en la fase 2." /></Panel>
        : setup.isPending ? <Panel className="p-4"><Skeleton cols={3} rows={5} /></Panel>
        : setup.isError ? <Panel><ErrorState message={setup.error.message} onRetry={() => void setup.refetch()} /></Panel>
        : s && (
        <>
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
            <Panel className="p-4">
              <h2 className="mb-2 text-[14px] font-semibold">Entrada</h2>
              <Tabs label="Tipo de entrada" value={mode} onChange={setMode} tabs={[{ id: 'cve', label: 'CVE del dataset' }, { id: 'manual', label: 'Valores a mano' }]} />
              <div className="mt-3">
                {mode === 'cve' ? (
                  <div className="space-y-3">
                    <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); search.mutate() }}>
                      <div className="flex-1"><Field label="CVE (o su comienzo)"><Input value={q} onChange={(e) => setQ(e.target.value)} className="font-mono" minLength={9} maxLength={16} pattern="[Cc][Vv][Ee]-\d{4}-\d{0,7}" required /></Field></div>
                      <Button type="submit" disabled={search.isPending}>{search.isPending ? 'Buscando…' : 'Buscar'}</Button>
                    </form>
                    {cases && (cases.length === 0 ? <p className="text-[12px] text-muted">Sin coincidencias. Los CVE que no entraron a KEV están muestreados: no todos aparecen.</p> : (
                      <ul className="max-h-72 divide-y divide-line overflow-y-auto rounded-lg border border-line" aria-label="Coincidencias">
                        {cases.map((c) => (
                          <li key={`${c.cve}-${c.snapshot}`}>
                            <button type="button" onClick={() => predict.mutate({ cve: c.cve, snapshot: c.snapshot })}
                              className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[13px] transition-colors duration-150 hover:bg-sunken pointer-coarse:py-3">
                              <span className="font-mono">{c.cve}</span>
                              <span className="text-[12px] text-muted">{c.snapshot.slice(0, 7)} · {SPLIT[c.split] ?? c.split}{c.label ? ' · entró a KEV' : ''}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    ))}
                  </div>
                ) : (
                  <ManualForm setup={s} values={form} onChange={setValues} busy={predict.isPending} onSubmit={() => predict.mutate({ values: form })} />
                )}
              </div>
            </Panel>
            <Panel className="min-w-0 p-4">
              <h2 className="mb-2 text-[14px] font-semibold">Predicción</h2>
              <div aria-live="polite">
                {predict.isPending ? <Skeleton cols={2} rows={4} /> : pred ? (
                  <Result p={pred} horizon={s.horizon_days} how={s.how_to_read} onScenario={() => { setValues({ ...pred.values }); setMode('manual') }} />
                ) : <EmptyState compact title="Elija un CVE o ingrese valores" hint="Verá la probabilidad calibrada, su severidad y qué la explica." />}
              </div>
            </Panel>
          </div>

          <Panel className="p-4">
            <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="text-[14px] font-semibold">Más probables en una foto</h2>
                {ranking.data && <p className="text-[12px] text-muted">Foto de {SPLIT[ranking.data.split]}: de los {ranking.data.rows.length} primeros entraron a KEV {ranking.data.hits}, de {ranking.data.positives} entradas en la foto.</p>}
              </div>
              {ranking.data && (
                <div className="w-44"><Select aria-label="Foto" value={ranking.data.snapshot} onChange={(e) => setShot(e.target.value)}>{ranking.data.snapshots.map((x) => <option key={x} value={x}>{x.slice(0, 7)}</option>)}</Select></div>
              )}
            </div>
            {ranking.isPending ? <Skeleton cols={4} rows={5} /> : ranking.isError ? <ErrorState message={ranking.error.message} onRetry={() => void ranking.refetch()} /> : (
              <div className="max-h-96 overflow-auto">
                <table className="w-full text-[13px]">
                  <thead><tr><th className={th}>#</th><th className={th}>CVE</th><th className={`${th} text-right`}>Probabilidad</th><th className={th}>Severidad</th><th className={th}>Resultado real</th></tr></thead>
                  <tbody>
                    {ranking.data.rows.map((r, i) => (
                      <tr key={r.cve} className="cursor-pointer transition-colors duration-150 hover:bg-sunken" tabIndex={0}
                        onClick={() => predict.mutate({ cve: r.cve, snapshot: ranking.data.snapshot })}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); predict.mutate({ cve: r.cve, snapshot: ranking.data.snapshot }) } }}>
                        <td className={`${td} tabular-nums text-muted`}>{i + 1}</td>
                        <td className={`${td} font-mono`}>{r.cve}</td>
                        <td className={`${td} text-right tabular-nums`}>{pct(r.probability)}</td>
                        <td className={td}><Badge band={r.band} /></td>
                        <td className={`${td} text-muted`}>{r.label ? 'Entró a KEV' : 'No entró'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Calibration setup={s} />
        </>
      )}
    </div>
  )
}
