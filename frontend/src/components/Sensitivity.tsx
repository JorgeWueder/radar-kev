// Análisis de sensibilidad de los pesos del score: configuración de la búsqueda, pruebas y resultados. Solo consulta.
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, XAxis, YAxis, ZAxis } from 'recharts'
import { toast } from 'sonner'

import { api } from '../lib/api'
import { num } from './Descriptive'
import { Button, Field, Input, Panel, td, th } from './ui'

type W = 'w_epss' | 'w_percentile' | 'w_cvss' | 'w_asset'
interface Trial { trial: number; w_epss: number; w_percentile: number; w_cvss: number; w_asset: number; spearman: number; top_overlap: number; band_changes: number; auc: number | null; current: boolean }
export interface SensitivityResult {
  n_findings: number; top_k?: number; elapsed_ms?: number; trials: Trial[]; current: Trial | null; best: Trial[]
  importance: { weight: W; label: string; pct: number }[]; interpretation: string[]
  how_to_read: { trials: string; importance: string; best: string }
}

const WEIGHTS: [W, string][] = [['w_epss', 'EPSS'], ['w_percentile', 'Percentil'], ['w_cvss', 'CVSS'], ['w_asset', 'Activo']]
const SIZES = [50, 200, 500] as const
/** Mínimo del eje redondeado hacia abajo a 0,05; el máximo es 1 (ni Spearman ni AUC lo superan). */
const floor05 = (min: number) => Math.max(0, Math.floor(min * 20) / 20)

function How({ children }: { children: string }) {
  return <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{children}</p></details>
}

function TrialTable({ rows, k }: { rows: Trial[]; k: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr>
            <th className={th}>Prueba</th>
            {WEIGHTS.map(([w, l]) => <th key={w} className={`${th} text-right`}>{l}</th>)}
            <th className={`${th} text-right`}>Spearman</th><th className={`${th} text-right`}>Top {k}</th><th className={`${th} text-right`}>Cambian de banda</th><th className={`${th} text-right`}>AUC</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.trial}>
              <td className={`${td} ${t.current ? 'font-semibold' : ''}`}>{t.current ? 'Vigente' : `#${t.trial}`}</td>
              {WEIGHTS.map(([w]) => <td key={w} className={`${td} text-right tabular-nums`}>{num(t[w], '', 3).replace(/,?0+$/, '') || '0'}</td>)}
              <td className={`${td} text-right tabular-nums`}>{num(t.spearman, '', 2)}</td>
              <td className={`${td} text-right tabular-nums`}>{t.top_overlap}/{k}</td>
              <td className={`${td} text-right tabular-nums`}>{t.band_changes}</td>
              <td className={`${td} text-right tabular-nums`}>{num(t.auc, '', 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function SensitivityPanel() {
  const [n, setN] = useState<(typeof SIZES)[number]>(200)
  const [seed, setSeed] = useState(7)
  const [bounds, setBounds] = useState<Record<W, [number, number]>>({ w_epss: [0, 1], w_percentile: [0, 1], w_cvss: [0, 1], w_asset: [0, 1] })
  const run = useMutation({
    mutationFn: () => api.post<SensitivityResult>('/settings/scoring/sensitivity', { n_trials: n, seed, bounds }),
    onError: (e) => toast.error((e as Error).message),
  })
  const setBound = (w: W, i: 0 | 1, v: string) => {
    const next = [...bounds[w]] as [number, number]
    next[i] = Math.min(1, Math.max(0, Number(v)))
    setBounds({ ...bounds, [w]: next })
  }
  const d = run.data
  const k = d?.top_k ?? 10
  const others = d?.trials.filter((t) => !t.current && t.auc !== null) ?? []
  const current = d?.current && d.current.auc !== null ? [d.current] : []

  return (
    <div className="space-y-4">
      <Panel className="p-4">
        <h2 className="text-[14px] font-semibold">¿Cuánto dependen las prioridades de los pesos?</h2>
        <p className="mb-3 text-[12px] text-muted">
          Prueba combinaciones de pesos al azar (que suman 1) y recalcula el score de los hallazgos abiertos con la misma fórmula, para ver cuánto cambiaría el orden de prioridad frente a la configuración vigente. Solo consulta: no guarda nada.
        </p>
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <p className="mb-1 text-[12px] text-muted">Número de pruebas</p>
            <div role="group" aria-label="Número de pruebas" className="flex gap-1">
              {SIZES.map((s) => (
                <button key={s} type="button" aria-pressed={n === s} onClick={() => setN(s)}
                  className={`h-8 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-11 ${n === s ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>{s}</button>
              ))}
            </div>
          </div>
          <div className="w-28"><Field label="Semilla"><Input type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} className="tabular-nums" /></Field></div>
          <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'Probando…' : 'Ejecutar análisis'}</Button>
        </div>
        <details className="mt-3 text-[13px]">
          <summary className="cursor-pointer select-none text-muted hover:text-ink">Rangos de búsqueda por peso</summary>
          <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
            {WEIGHTS.map(([w, l]) => (
              <fieldset key={w} className="min-w-0">
                <legend className="mb-1 text-[12px] text-muted">{l}</legend>
                <div className="flex gap-1">
                  <Input aria-label={`${l}: mínimo`} type="number" min={0} max={1} step={0.05} value={bounds[w][0]} onChange={(e) => setBound(w, 0, e.target.value)} className="tabular-nums" />
                  <Input aria-label={`${l}: máximo`} type="number" min={0} max={1} step={0.05} value={bounds[w][1]} onChange={(e) => setBound(w, 1, e.target.value)} className="tabular-nums" />
                </div>
              </fieldset>
            ))}
          </div>
        </details>
      </Panel>

      {d && (
        <>
          <Panel className="p-4">
            <h3 className="text-[13px] font-semibold">Lectura de los resultados</h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px]">{d.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>
          </Panel>
          {d.trials.length > 0 && (
            <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
              <Panel className="p-4">
                <h3 className="mb-1 text-[13px] font-semibold">Pruebas: parecido al orden vigente frente a AUC</h3>
                {others.length ? (
                  <figure aria-label={`${others.length} pruebas; la vigente tiene Spearman 1 y AUC ${num(d.current?.auc, '', 2)}`}>
                    <ResponsiveContainer width="100%" height={240}>
                      <ScatterChart margin={{ top: 8, right: 20, bottom: 14, left: -12 }}>
                        <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
                        <XAxis type="number" dataKey="spearman" name="Spearman" domain={[floor05, 1]} tickFormatter={(v: number) => num(v, '', 2)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false}
                          label={{ value: 'Parecido al orden vigente (Spearman)', position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
                        <YAxis type="number" dataKey="auc" name="AUC" domain={[floor05, 1]} tickFormatter={(v: number) => num(v, '', 2)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
                        <ZAxis range={[28, 28]} />
                        <Scatter data={others} fill="var(--accent)" fillOpacity={0.45} isAnimationActive={false} name="Pruebas" />
                        <Scatter data={current} fill="var(--ink)" shape="diamond" isAnimationActive={false} name="Vigente" legendType="diamond" />
                      </ScatterChart>
                    </ResponsiveContainer>
                    <figcaption className="mt-1 flex gap-4 text-[12px] text-muted">
                      <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-accent opacity-60" aria-hidden /> Prueba</span>
                      <span className="flex items-center gap-1.5"><span className="size-2.5 rotate-45 bg-ink" aria-hidden /> Vigente</span>
                    </figcaption>
                  </figure>
                ) : <p className="text-[13px] text-muted">Sin AUC (hacen falta CVE dentro y fuera de KEV): no se dibuja el gráfico.</p>}
                <How>{d.how_to_read.trials}</How>
              </Panel>
              <Panel className="p-4">
                <h3 className="mb-2 text-[13px] font-semibold">Importancia de cada peso</h3>
                <ul className="space-y-2">
                  {d.importance.map((x) => (
                    <li key={x.weight} className="grid grid-cols-[130px_1fr_44px] items-center gap-2 text-[13px]">
                      <span className="text-muted">{x.label}</span>
                      <span className="h-2 rounded-sm bg-sunken" role="presentation"><span className="block h-2 rounded-sm bg-accent" style={{ width: `${x.pct}%` }} /></span>
                      <span className="text-right tabular-nums">{num(x.pct, '%', 0)}</span>
                    </li>
                  ))}
                </ul>
                <How>{d.how_to_read.importance}</How>
              </Panel>
            </div>
          )}
          {d.current && (
            <Panel className="p-4">
              <h3 className="mb-1 text-[13px] font-semibold">Vigente y mejores combinaciones estables</h3>
              <TrialTable rows={[d.current, ...d.best]} k={k} />
              <How>{d.how_to_read.best}</How>
              <details className="mt-2 text-[13px]">
                <summary className="cursor-pointer select-none text-muted hover:text-ink">Ver las {d.trials.length - 1} pruebas</summary>
                <div className="mt-2 max-h-96 overflow-y-auto"><TrialTable rows={d.trials} k={k} /></div>
              </details>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}
