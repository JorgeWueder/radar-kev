// Prueba prospectiva de EPSS sobre todo el universo de CVE: ¿el EPSS de hace N días anticipaba las entradas a KEV?
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDate, formatLima } from '../lib/format'
import { num } from './Descriptive'
import { Button, Panel, Skeleton, td, th } from './ui'

interface Effort { share_pct: number; cves: number; captured: number; coverage_pct: number; precision_pct: number; lift: number }
interface Rule { threshold_pct: number; marked: number; effort_pct: number; captured: number; coverage_pct: number; precision_pct: number | null }
export interface UniverseResult {
  as_of: string; until: string; horizon_days: number; n: number; excluded_known: number; positives: number; not_scored: number
  auc: number | null; auc_ci: [number, number] | null; effort: Effort[]; rules: Rule[]; interpretation: string[]
  how_to_read: { effort: string; rules: string }; computed_at: string; model_version: string | null
}

const HORIZONS = [30, 90, 180] as const
const int = (n: number) => n.toLocaleString('es-PE').replace(/[,.]/g, ' ')

export function UniversePanel() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [horizon, setHorizon] = useState<(typeof HORIZONS)[number]>(90)
  const q = useQuery({ queryKey: ['dash-universe'], queryFn: () => api.get<UniverseResult | null>('/dashboard/evaluation/universe') })
  const run = useMutation({
    mutationFn: () => api.post<UniverseResult>(`/dashboard/evaluation/universe?horizon=${horizon}`),
    onSuccess: (d) => { qc.setQueryData(['dash-universe'], d); toast.success(`Prueba calculada con ${int(d.n)} CVE`) },
    onError: (e) => toast.error((e as Error).message),
  })
  const d = q.data
  return (
    <Panel className="mt-4 p-4">
      <section aria-labelledby="univ-title">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1 basis-80">
            <h2 id="univ-title" className="text-[14px] font-semibold">¿EPSS anticipa lo que entrará a KEV? Prueba sobre todo el universo de CVE</h2>
            <p className="text-[12px] text-muted">
              Se toma el EPSS publicado hace N días para todos los CVE, se quitan los que ya estaban en KEV y se mide si anticipaba los que entraron después. Es una prueba prospectiva: EPSS no podía ver la respuesta.
            </p>
          </div>
          {can('workflow', 'create') && (
            <div className="flex items-center gap-2">
              <div role="group" aria-label="Horizonte de la prueba" className="flex gap-1">
                {HORIZONS.map((h) => (
                  <button key={h} type="button" aria-pressed={horizon === h} onClick={() => setHorizon(h)}
                    className={`h-7 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-10 ${horizon === h ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>
                    {h} días
                  </button>
                ))}
              </div>
              <Button onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? 'Calculando…' : 'Calcular'}</Button>
            </div>
          )}
        </div>

        {q.isPending ? <Skeleton cols={2} rows={3} /> : !d ? (
          <p className="mt-3 text-[13px] text-muted">
            Aún no se ha calculado. {can('workflow', 'create') ? 'Elija el horizonte y pulse «Calcular»: descarga el EPSS histórico completo (cientos de miles de CVE) y tarda unos segundos.' : 'Pida a un analista que la calcule.'}
          </p>
        ) : (
          <>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] sm:grid-cols-4">
              <div><dt className="text-[12px] text-muted">EPSS del</dt><dd className="font-medium tabular-nums">{formatDate(d.as_of)}</dd></div>
              <div><dt className="text-[12px] text-muted">CVE evaluados</dt><dd className="font-medium tabular-nums">{int(d.n)}</dd></div>
              <div><dt className="text-[12px] text-muted">Entraron a KEV en {d.horizon_days} días</dt><dd className="font-medium tabular-nums">{d.positives}</dd></div>
              <div><dt className="text-[12px] text-muted">AUC (IC 95 %)</dt><dd className="font-medium tabular-nums">{num(d.auc, '', 2)}{d.auc_ci && <span className="font-normal text-muted"> ({num(d.auc_ci[0], '', 2)} a {num(d.auc_ci[1], '', 2)})</span>}</dd></div>
            </dl>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-[13px]">{d.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>

            {d.effort.length > 0 && (
              <div className="mt-4 grid gap-4 xl:grid-cols-2">
                <div>
                  <h3 className="mb-1 text-[13px] font-semibold">Esfuerzo frente a cobertura</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[13px]">
                      <thead><tr><th className={th}>Parchear el primer</th><th className={`${th} text-right`}>CVE</th><th className={`${th} text-right`}>Entradas cubiertas</th><th className={`${th} text-right`}>Veces mejor que el azar</th></tr></thead>
                      <tbody>
                        {d.effort.map((e) => (
                          <tr key={e.share_pct}>
                            <td className={td}>{num(e.share_pct, '%')}</td>
                            <td className={`${td} text-right tabular-nums`}>{int(e.cves)}</td>
                            <td className={`${td} text-right tabular-nums`}>{e.captured} <span className="text-muted">({num(e.coverage_pct, '%', 0)})</span></td>
                            <td className={`${td} text-right tabular-nums`}>{num(e.lift, '', 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{d.how_to_read.effort}</p></details>
                </div>
                <div>
                  <h3 className="mb-1 text-[13px] font-semibold">Reglas por umbral de EPSS</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[13px]">
                      <thead><tr><th className={th}>Regla</th><th className={`${th} text-right`}>CVE marcados</th><th className={`${th} text-right`}>Esfuerzo</th><th className={`${th} text-right`}>Cobertura</th></tr></thead>
                      <tbody>
                        {d.rules.map((r) => (
                          <tr key={r.threshold_pct}>
                            <td className={td}>EPSS ≥ {num(r.threshold_pct, '%', 0)}</td>
                            <td className={`${td} text-right tabular-nums`}>{int(r.marked)}</td>
                            <td className={`${td} text-right tabular-nums`}>{num(r.effort_pct, '%')}</td>
                            <td className={`${td} text-right tabular-nums`}>{r.captured} <span className="text-muted">({num(r.coverage_pct, '%', 0)})</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{d.how_to_read.rules}</p></details>
                </div>
              </div>
            )}
            <p className="mt-3 text-[12px] text-muted">
              Calculado {formatLima(d.computed_at)} · KEV hasta {formatDate(d.until)}{d.model_version ? ` · modelo EPSS ${d.model_version}` : ''}.
            </p>
          </>
        )}
      </section>
    </Panel>
  )
}
