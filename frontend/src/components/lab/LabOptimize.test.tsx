import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { LabOptimize, pv, type Study } from './LabOptimize'
import type { Dataset } from './types'

const DS = { id: 'd2', name: 'KEV en 90 días v2', status: 'ready', tags: [], params: {}, stats: {} } as unknown as Dataset
const ALGOS = [{ key: 'logreg', label: 'Regresión logística', limits: { C: { low: 1e-5, high: 100 } },
  space: [{ name: 'C', type: 'float_log', low: 0.001, high: 10, default: 1, description: '' }, { name: 'class_weight', type: 'cat', choices: ['balanced', 'none'], default: 'balanced', description: '' }] }]
const trial = (number: number, value: number, C: number, best: number) => ({ number, state: 'completa', value, params: { C, class_weight: 'balanced' }, folds: [value, value], seconds: 2, best, default: number === 0 })
const STUDY: Study = {
  id: 's1', dataset_id: 'd2', algorithm: 'logreg', name: 'Regresión logística · TPE (bayesiano) · 3 pruebas', status: 'done',
  config: { sampler: 'tpe', pruner: 'median', n_trials: 3, timeout_minutes: 30, seed: 7, k_in: 3, include_defaults: true, drop: [] },
  best_params: { C: 0.0012, class_weight: 'balanced' }, best_value: 0.08, seconds: 30, error: null, stop_requested: false, n_done: 3, created_at: null,
  space: ALGOS[0].space as Study['space'],
  trials: [trial(0, 0.05, 1, 0.05), trial(1, 0.08, 0.0012, 0.08), trial(2, 0.06, 0.3, 0.08)] as Study['trials'],
  summary: { n_trials: 3, n_complete: 3, n_pruned: 0, n_failed: 0, importance: [{ param: 'C', value: 0.9 }, { param: 'class_weight', value: 0.1 }],
    edges: [{ param: 'C', side: 'inferior', value: 0.0012, low: 0.001, high: 10, suggest: { low: 0.0001, high: 10 }, at_limit: false }],
    reading: ['Mejor PR-AUC interna 0,0800 en la prueba 1 (3 completas).'], how_to_read: {} },
}
// Recién lanzado: el backend devuelve summary = {} hasta que termina.
const RUNNING = { ...STUDY, id: 's2', status: 'running', trials: STUDY.trials?.slice(0, 1), summary: {} } as unknown as Study
const posts: unknown[][] = []
vi.mock('../../lib/api', () => ({
  api: {
    get: (path: string) => Promise.resolve(path === '/ml/algorithms' ? ALGOS : path === '/ml/studies' ? [{ ...STUDY, trials: undefined, space: undefined, summary: undefined }]
      : path === '/ml/studies/s2' ? RUNNING : STUDY),
    post: (...args: unknown[]) => { posts.push(args); return Promise.resolve({ study_id: 's2', job_id: 'j', model_id: 'm9' }) },
  },
}))
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ can: () => true }) }))
vi.mock('sonner', () => ({ toast: { success: () => undefined, error: () => undefined } }))
class RO { observe() {} unobserve() {} disconnect() {} }

describe('Laboratorio · Fase 7', () => {
  beforeAll(() => { globalThis.ResizeObserver = RO as unknown as typeof ResizeObserver })

  it('formatea hiperparámetros', () => {
    expect(pv(0.0012)).toBe('0,0012')
    expect(pv(200)).toBe('200')
    expect(pv(0.35)).toBe('0,35')
    expect(pv(4.33012)).toBe('4,33')
    expect(pv(0.0001)).toBe('0,0001')
  })

  it('muestra el estudio, sugiere ampliar el rango y entrena con el espacio', async () => {
    render(<QueryClientProvider client={new QueryClient()}><LabOptimize datasets={[DS]} /></QueryClientProvider>)
    expect(await screen.findByText('Mejor PR-AUC interna 0,0800 en la prueba 1 (3 completas).')).toBeInTheDocument()
    expect(screen.getByRole('figure', { name: 'Historial de optimización: 3 pruebas' })).toBeInTheDocument()
    expect(screen.getByText('C=0,0012 · class_weight=balanced', { selector: 'dd' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Usar [0,0001, 10]' }))
    expect(screen.getByLabelText('C mínimo')).toHaveValue(0.0001)
    fireEvent.click(screen.getByRole('button', { name: 'Iniciar estudio' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0][0]).toBe('/ml/studies')
    expect(posts[0][1]).toMatchObject({ dataset_id: 'd2', algorithm: 'logreg', sampler: 'tpe', space: { C: { low: 0.0001, high: 10 }, class_weight: { choices: ['balanced', 'none'] } } })

    expect(await screen.findByRole('button', { name: 'Detener' })).toBeInTheDocument() // el estudio nuevo, en curso, no rompe la vista
    expect(screen.getByText('1 de 3 pruebas · 1 completas')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Regresión logística · TPE/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Entrenar con este espacio' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]).toEqual(['/ml/models', { dataset_id: 'd2', algorithm: 'logreg', n_trials: 15, seed: 7, drop: [], study_id: 's1',
      space: { C: { low: 0.001, high: 10 }, class_weight: { choices: ['balanced', 'none'] } } }])
  })
})
