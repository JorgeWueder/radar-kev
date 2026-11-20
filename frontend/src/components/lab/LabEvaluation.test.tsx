import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'

import { type EvalResult, LabEvaluation } from './LabEvaluation'
import type { Dataset } from './types'

const DS = { id: 'd2', name: 'KEV en 90 días v2', status: 'ready', tags: [], params: {}, stats: {} } as unknown as Dataset
const m = (pr: number, roc: number) => ({ rows: 51_777, positives: 93, prevalence_pct: 0.009, pr_auc: pr, roc_auc: roc, recall_1pct: 0.34, recall_5pct: 0.5 })
const conf = { raw: { tp: 32, fp: 480, fn: 61, tn: 51_204 }, estimated: { tp: 32, fp: 9_600, fn: 61, tn: 1_024_080 }, recall: 0.344, precision: 0.0033, effort_pct: 0.94, threshold: 0.2 }
const curve = { roc: [{ fpr: 0, tpr: 0 }, { fpr: 1, tpr: 1 }], pr: [{ recall: 0, precision: 1 }, { recall: 1, precision: 0.0001 }] }
const R: EvalResult = {
  operating_pct: 1, best: 'm1', test_best: 'm1', test_prevalence_pct: 0.009, interpretation: ['En prueba (meses nunca vistos), el mejor modelo es Gradient boosting.'],
  how_to_read: { metrics: 'm', confusion: 'c', curves: 'k', friedman: 'f', bootstrap: 'b', mcnemar: 'n', stability: 's' },
  rows: [
    { key: 'm1', label: 'Gradient boosting', kind: 'modelo', test: m(0.0017, 0.852), validation: m(0.019, 0.954) },
    { key: 'epss', label: 'EPSS (sin entrenar)', kind: 'base', test: m(0.0004, 0.70), validation: m(0.003, 0.70) },
    { key: 'cvss', label: 'CVSS de la CNA (sin entrenar)', kind: 'base', test: m(0.0001, 0.66), validation: m(0.0001, 0.66) },
  ],
  confusion: { m1: conf, epss: conf, cvss: conf }, curves: { m1: curve, epss: curve, cvss: curve },
  pairs: [{ a: 'm1', b: 'epss', b_label: 'EPSS (sin entrenar)', pr_auc: { diff: 0.0013, ci: [0.0002, 0.003], p: 0.01 }, roc_auc: { diff: 0.15, ci: [0.1, 0.2], p: 0 }, mcnemar: { only_a: 20, only_b: 3, p: 0.0004 } }],
  friedman: { stat: 12.4, p: 0.002, keys: ['m1', 'epss', 'cvss'], mean_rank: { m1: 1, epss: 2, cvss: 3 } },
  stability: [{ snapshot: '2026-06-01', positives: 24, epss_model: 'v2025.03.14', m1: 0.004, epss: 0.001, cvss: 0.0001 }, { snapshot: '2026-07-01', positives: 32, epss_model: 'v2026.06.15', m1: 0.0009, epss: 0.0003, cvss: 0.0001 }],
  models: [{ id: 'm1', name: 'Gradient boosting', algorithm: 'hgb', drop: [] }],
}

vi.mock('../../lib/api', () => ({ api: { get: () => Promise.resolve(R) } }))
class RO { observe() {} unobserve() {} disconnect() {} }

describe('Laboratorio · Fase 3', () => {
  beforeAll(() => { globalThis.ResizeObserver = RO as unknown as typeof ResizeObserver })

  it('muestra métricas en prueba, matrices, pruebas estadísticas y estabilidad con la versión de EPSS', async () => {
    render(<QueryClientProvider client={new QueryClient()}><LabEvaluation datasets={[DS]} /></QueryClientProvider>)
    expect(await screen.findByText(/el mejor modelo es Gradient boosting/)).toBeInTheDocument()
    expect(screen.getAllByText('Gradient boosting')[0].closest('tr')).toHaveTextContent('0,00170,852')
    expect(screen.getByRole('table', { name: 'Matriz de confusión: Gradient boosting' })).toHaveTextContent('Marcado32480')
    expect(screen.getByText(/χ² = 12,4 · p = 0,002/)).toBeInTheDocument()
    expect(screen.getByText('v2026.06.15')).toBeInTheDocument()
    expect(screen.getAllByText(/20 \/ 3/).length).toBeGreaterThan(0)
  })
})
