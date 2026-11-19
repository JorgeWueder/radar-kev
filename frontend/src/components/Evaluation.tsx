// Evaluación de criterios de priorización frente a KEV: ROC/AUC, precisión-cobertura y reglas con matriz de confusión.
import { useQuery } from '@tanstack/react-query'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts'

import { api } from '../lib/api'
import { num } from './Descriptive'
import { ErrorState, Panel, Skeleton, td, th } from './ui'

interface Predictor { key: 'cvss' | 'epss' | 'base'; label: string; auc: number | null; auc_ci: [number, number] | null; ap: number | null; roc: { fpr: number; tpr: number }[]; pr: { recall: number; precision: number }[] }
interface Rule { key: string; label: string; tp: number; fp: number; fn: number; tn: number; coverage: number | null; efficiency: number | null; effort: number | null }
export interface Evaluation {
  n: number; positives: number; negatives?: number; prevalence?: number; reliable: boolean
  predictors: Predictor[]; rules: Rule[]; interpretation: string[]; how_to_read: { roc: string; pr: string; rules: string }
}

/** Tres series distinguibles sin depender solo del color: trazo, grosor y guiones. */
const SERIES: Record<Predictor['key'], { stroke: string; dash?: string; width: number }> = {
  epss: { stroke: 'var(--accent)', width: 2.5 },
  base: { stroke: 'var(--ink)', dash: '6 3', width: 2 },
  cvss: { stroke: 'var(--muted)', dash: '2 3', width: 2 },
}

const pct = (v: number) => `${Math.round(v * 100)} %`

function Legend({ preds }: { preds: Predictor[] }) {
  return (
    <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
      {preds.map((p) => {
        const s = SERIES[p.key]
        return (
          <li key={p.key} className="flex items-center gap-1.5">
            <svg width="18" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" stroke={s.stroke} strokeWidth={s.width} strokeDasharray={s.dash} /></svg>
            {p.label}
          </li>
        )
      })}
    </ul>
  )
}

function Curve({ title, preds, kind, baseline, how }: { title: string; preds: Predictor[]; kind: 'roc' | 'pr'; baseline: number; how: string }) {
  const summary = preds.map((p) => `${p.label}: ${kind === 'roc' ? `AUC ${num(p.auc, '', 2)}` : `precisión media ${num(p.ap, '', 2)}`}`).join('; ')
  return (
    <figure aria-label={`${title}. ${summary}`}>
      <h3 className="mb-1 text-[13px] font-semibold">{title}</h3>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart margin={{ top: 6, right: 12, bottom: 14, left: -12 }}>
          <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" />
          <XAxis type="number" dataKey={kind === 'roc' ? 'fpr' : 'recall'} domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={pct}
            tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={{ stroke: 'var(--line)' }}
            label={{ value: kind === 'roc' ? 'Otros CVE arrastrados' : 'Cobertura de KEV', position: 'insideBottom', offset: -8, fill: 'var(--muted)', fontSize: 11 }} />
          <YAxis type="number" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={pct} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
          {kind === 'roc'
            ? <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="var(--line-strong)" strokeDasharray="3 3" ifOverflow="extendDomain" />
            : <ReferenceLine y={baseline} stroke="var(--line-strong)" strokeDasharray="3 3" />}
          {preds.map((p) => {
            const s = SERIES[p.key]
            return (
              <Line key={p.key} data={kind === 'roc' ? p.roc : p.pr} dataKey={kind === 'roc' ? 'tpr' : 'precision'} name={p.label}
                type={kind === 'roc' ? 'linear' : 'stepAfter'} stroke={s.stroke} strokeWidth={s.width} strokeDasharray={s.dash} dot={false} isAnimationActive={false} />
            )
          })}
        </LineChart>
      </ResponsiveContainer>
      <figcaption>
        <Legend preds={preds} />
        <p className="mt-1 text-[12px] text-muted">{kind === 'roc' ? 'La diagonal es el azar.' : `La línea horizontal es la proporción de KEV (${pct(baseline)}).`}</p>
        <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{how}</p></details>
      </figcaption>
    </figure>
  )
}

/** Una regla: tres métricas y su matriz de confusión 2×2 (filas: marcado o no; columnas: en KEV o no). */
function RuleCard({ r }: { r: Rule }) {
  const cell = 'px-2 py-1.5 text-right tabular-nums'
  return (
    <li className="rounded-lg border border-line p-3">
      <h4 className="text-[13px] font-medium">{r.label}</h4>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-[13px]">
        {([['Cobertura', r.coverage], ['Precisión', r.efficiency], ['Esfuerzo', r.effort]] as const).map(([k, v]) => (
          <div key={k}><dt className="text-[12px] text-muted">{k}</dt><dd className="font-medium tabular-nums">{num(v, '%', 0)}</dd></div>
        ))}
      </dl>
      <table className="mt-2 w-full text-[12px]" aria-label={`Matriz de confusión: ${r.label}`}>
        <thead>
          <tr className="text-muted"><td /><th scope="col" className="px-2 py-1 text-right font-normal">En KEV</th><th scope="col" className="px-2 py-1 text-right font-normal">Otros</th></tr>
        </thead>
        <tbody className="border-t border-line">
          <tr><th scope="row" className="py-1.5 pr-2 text-left font-normal text-muted">Marcados</th><td className={cell}>{r.tp}</td><td className={cell}>{r.fp}</td></tr>
          <tr className="border-t border-line">
            <th scope="row" className="py-1.5 pr-2 text-left font-normal text-muted">Sin marcar</th>
            <td className={`${cell} ${r.fn ? 'font-semibold' : ''}`}>{r.fn}</td><td className={cell}>{r.tn}</td>
          </tr>
        </tbody>
      </table>
    </li>
  )
}

export function EvaluationPanel() {
  const q = useQuery({ queryKey: ['dash-evaluation'], queryFn: () => api.get<Evaluation>('/dashboard/evaluation') })
  if (q.isPending) return <Panel className="mt-4 p-4"><Skeleton cols={2} rows={4} /></Panel>
  if (q.isError) return <Panel className="mt-4"><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></Panel>
  const d = q.data
  if (!d.n) return null
  const preds = [...d.predictors].sort((a, b) => (b.auc ?? 0) - (a.auc ?? 0))
  return (
    <Panel className="mt-4 p-4">
      <section aria-labelledby="eval-title">
        <h2 id="eval-title" className="text-[14px] font-semibold">¿Qué criterio encuentra lo que ya explotan?</h2>
        <p className="mb-3 text-[12px] text-muted">
          CVSS, EPSS y el score sin KEV, evaluados contra la explotación confirmada (KEV), por CVE único. El score completo no se evalúa: incluye KEV y saldría perfecto por construcción.
        </p>
        <ul className="mb-4 list-disc space-y-1 pl-5 text-[13px]">{d.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>

        {preds.length > 0 && (
          <>
            <div className="mb-4 overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead><tr><th className={th}>Criterio</th><th className={`${th} text-right`}>AUC</th><th className={`${th} text-right`}>IC 95 %</th><th className={`${th} text-right`}>Precisión media</th></tr></thead>
                <tbody>
                  {preds.map((p) => (
                    <tr key={p.key}>
                      <td className={td}>{p.label}</td>
                      <td className={`${td} text-right font-medium tabular-nums`}>{num(p.auc, '', 2)}</td>
                      <td className={`${td} text-right tabular-nums`}>{p.auc_ci ? `${num(p.auc_ci[0], '', 2)} a ${num(p.auc_ci[1], '', 2)}` : '—'}</td>
                      <td className={`${td} text-right tabular-nums`}>{num(p.ap, '', 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid gap-6 lg:grid-cols-2">
              <Curve title="Curva ROC" preds={preds} kind="roc" baseline={0} how={d.how_to_read.roc} />
              <Curve title="Precisión frente a cobertura" preds={preds} kind="pr" baseline={(d.prevalence ?? 0) / 100} how={d.how_to_read.pr} />
            </div>

            <h3 className="mb-1 mt-6 text-[13px] font-semibold">Reglas fijas: matriz de confusión</h3>
            <ul className="grid gap-3 sm:grid-cols-2">
              {d.rules.map((r) => <RuleCard key={r.key} r={r} />)}
            </ul>
            <p className="mt-2 text-[12px] text-muted">"KEV sin marcar" es explotación real que la regla dejaría pasar (en negrita cuando hay alguno).</p>
            <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{d.how_to_read.rules}</p></details>
          </>
        )}
      </section>
    </Panel>
  )
}
