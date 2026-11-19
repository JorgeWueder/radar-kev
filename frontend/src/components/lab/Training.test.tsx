import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import { type Model, Training } from './Training'
import type { Dataset } from './types'

const DS: Dataset = {
  id: 'd2', name: 'KEV en 90 días v2', description: '', notes: '', tags: [], status: 'ready', created_at: null, updated_at: null, sources: [],
  params: { start: '2025-01-01', until: '2026-11-18', horizon_days: 90, neg_rate: 0.05, seed: 7, snapshots: 20, split: 'temporal 70/15/15' },
  stats: { by_split: { desarrollo: { rows: 201_036, positives: 418, snapshots: 14 }, validacion: { rows: 48_354, positives: 91, snapshots: 3 }, prueba: { rows: 51_777, positives: 93, snapshots: 3 } } },
}
const ALGOS = [
  { key: 'logreg', label: 'Regresión logística', family: 'Lineal', description: 'Modelo lineal', defaults: { C: 1 },
    space: [{ name: 'C', type: 'float_log', low: 0.001, high: 10, default: 1, description: 'Inverso de la regularización' }] },
  { key: 'hgb', label: 'Gradient boosting (histogramas)', family: 'Árboles', description: 'Boosting', defaults: { learning_rate: 0.08 },
    space: [{ name: 'learning_rate', type: 'float_log', low: 0.02, high: 0.3, default: 0.08, description: 'Tamaño del paso' }] },
]
const m = (v: number) => ({ rows: 30_000, positives: 60, prevalence_pct: 0.01, pr_auc: v, roc_auc: 0.8, recall_1pct: 0.2, recall_5pct: 0.4 })
const MODEL: Model = {
  id: 'm1', dataset_id: 'd2', algorithm: 'hgb', name: 'Gradient boosting · 15 pruebas', status: 'ready', seconds: 360, error: null, created_at: '2026-11-19T22:00:00Z', finished_at: null,
  config: { n_trials: 15, k_out: 5, k_in: 3, seed: 7, metric: 'PR-AUC ponderada', cv: 'anidada temporal (ventana creciente)', target: 'entra a KEV en 90 días' },
  aggregate: { model: { pr_auc: { mean: 0.0123, sd: 0.004, n: 5 }, roc_auc: { mean: 0.81, sd: 0.03, n: 5 }, recall_1pct: { mean: 0.2, sd: 0.05, n: 5 }, recall_5pct: { mean: 0.4, sd: 0.05, n: 5 } },
    epss: { pr_auc: { mean: 0.004, sd: 0.002, n: 5 }, roc_auc: { mean: 0.66, sd: 0.04, n: 5 }, recall_1pct: { mean: 0.1, sd: 0.02, n: 5 }, recall_5pct: { mean: 0.2, sd: 0.03, n: 5 } }, wins_vs_epss: 5 },
  best_params: { learning_rate: 0.05, max_iter: 250 }, final_metrics: { validacion: m(0.015) }, reading: ['Supera a EPSS en 5 de 5 pliegues.'],
  folds: [{ fold: 1, train: ['2025-01-01', '2025-04-01'], val: ['2025-05-01', '2025-06-01'], train_rows: 60_000, train_positives: 116, best_params: { learning_rate: 0.1 }, metrics: m(0.011), baselines: { epss: m(0.004) } }],
  trials: [{ fold: 'Pliegue 1/5', trial: 0, value: 0.01, params: {}, seconds: 2 }],
}

vi.mock('../../lib/api', () => ({
  api: {
    get: (path: string) => Promise.resolve(path === '/ml/algorithms' ? ALGOS : path === '/ml/models' ? [MODEL] : path === '/ml/models/m1' ? MODEL : []),
    post: () => Promise.resolve({ model_id: 'm1', job_id: 'j1' }),
  },
}))
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ can: () => true }) }))
class RO { observe() {} unobserve() {} disconnect() {} }

describe('Laboratorio · Fase 2', () => {
  beforeAll(() => { globalThis.ResizeObserver = RO as unknown as typeof ResizeObserver })

  it('muestra la partición, los hiperparámetros del modelo elegido y el resultado por pliegue', async () => {
    render(<QueryClientProvider client={new QueryClient()}><Training datasets={[DS]} /></QueryClientProvider>)
    expect(screen.getByText(/Desarrollo 14 fotos \(418 KEV\)/)).toBeInTheDocument()
    expect((await screen.findAllByText('learning_rate')).length).toBe(2) // en la tabla y en su explicación
    fireEvent.click(screen.getByLabelText(/Regresión logística/))
    expect(screen.getByText('Hiperparámetros de Regresión logística')).toBeInTheDocument()
    expect(screen.getByText(/0,001 a 10 \(escala log\)/)).toBeInTheDocument()
    expect(await screen.findByText('Supera a EPSS en 5 de 5 pliegues.')).toBeInTheDocument()
    expect(screen.getByText('2025-05 a 2025-06')).toBeInTheDocument()
    expect(screen.getByText('Modelo entrenado').closest('tr')).toHaveTextContent('0,0123 ± 0,004')
    expect(screen.getByText(/Validación \(15 %\):/)).toBeInTheDocument()
  })
})
