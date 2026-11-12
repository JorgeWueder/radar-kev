// Comparación estadística del periodo actual frente al anterior (MTTR, SLA y tendencia de KEV).
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../lib/api'
import { formatDate } from '../lib/format'
import { ErrorState, Panel, Skeleton } from './ui'

interface Test { test: string; p_value: number | null; verdict?: string; trend?: string; interpretation: string }
interface Comparison {
  current: { start: string; end: string }; previous: { start: string; end: string }
  mttr: Test; sla: Test; kev_trend: Test
}

const RANGES = [30, 60, 90] as const

function verdictLabel(t: Test): string {
  if (t.verdict === 'sin_datos' || t.trend === 'sin_datos') return 'Sin datos suficientes'
  if (t.trend) return t.trend === 'sube' ? 'Sube' : t.trend === 'baja' ? 'Baja' : 'Sin tendencia'
  if (t.verdict === 'diferencia') return 'Diferencia real'
  if (t.verdict === 'diferencia_debil') return 'Indicio (pocos casos)'
  return 'Sin diferencia clara'
}

export function ComparisonPanel() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30)
  const q = useQuery({ queryKey: ['dash-comparison', days], queryFn: () => api.get<Comparison>('/dashboard/comparison', { days }) })
  const rows: [string, Test][] = q.data ? [['MTTR (días hasta mitigar)', q.data.mttr], ['Cumplimiento de SLA', q.data.sla], ['Tendencia de KEV abiertos', q.data.kev_trend]] : []
  return (
    <Panel className="mb-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-[14px] font-semibold">¿Mejoramos de verdad? Comparación con el periodo anterior</h2>
          <p className="mb-2 text-[12px] text-muted">
            {q.data ? `${formatDate(q.data.current.start)} a ${formatDate(q.data.current.end)} frente a ${formatDate(q.data.previous.start)} a ${formatDate(q.data.previous.end)}. ` : ''}
            Una variación solo cuenta si la prueba estadística la respalda; si no, puede ser azar.
          </p>
        </div>
        <div role="group" aria-label="Duración de los periodos" className="flex gap-1">
          {RANGES.map((r) => (
            <button key={r} type="button" aria-pressed={days === r} onClick={() => setDays(r)}
              className={`h-7 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-10 ${days === r ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>
              {r} días
            </button>
          ))}
        </div>
      </div>
      {q.isPending ? <Skeleton cols={1} rows={3} /> : q.isError ? <ErrorState message={q.error.message} onRetry={() => void q.refetch()} /> : (
        <ul className="divide-y divide-line">
          {rows.map(([label, t]) => (
            <li key={label} className="grid gap-1 py-2 text-[13px] md:grid-cols-[220px_1fr]">
              <div>
                <p className="font-medium">{label}</p>
                <p className="text-[12px] text-muted">{verdictLabel(t)}{t.p_value !== null && <span className="tabular-nums"> · {t.p_value < 0.001 ? 'p < 0,001' : `p = ${String(t.p_value).replace('.', ',')}`}</span>}</p>
              </div>
              <p>{t.interpretation} <span className="text-[12px] text-muted">({t.test})</span></p>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
