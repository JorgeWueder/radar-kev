import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { LabInference, type Prediction, type Setup } from './LabInference'
import type { Dataset } from './types'

const DS = { id: 'd2', name: 'KEV en 90 días v2', status: 'ready', tags: [], params: {}, stats: {} } as unknown as Dataset
const band = (key: string, label: string, share: number) => ({ key, label, meaning: '', share, rows: 10, positives: 5, rate: 0.003, rate_lo: 0.002, rate_hi: 0.005, pred: 0.004, lift: 35, recall: 0.25 })
const SETUP = {
  model: { id: 'm1', name: 'Random forest', algorithm: 'random_forest' }, dataset: { id: 'd2', name: 'KEV' }, horizon_days: 90, drop: [],
  calibration: {
    params: [1.5, 4], thresholds: { critica: 0.5, alta: 0.3, media: 0.1 }, base_rate: { validacion: 0.0001, prueba: 0.00009 },
    test: { observed: 93, expected: 126.5, oe: 0.73, oe_lo: 0.59, oe_hi: 0.9, slope: 1.09, slope_lo: 0.95, slope_hi: 1.23, brier_raw: 0.0001, brier_cal: 0.00009, brier_ref: 0.00009, brier_skill: 0.002, hl: 76.2, hl_df: 7, hl_p: 0.00001, positives: 93, rows: 51777 },
    bands: [band('critica', 'Crítica', 0.014), band('alta', 'Alta', 0.054), band('media', 'Media', 0.19), band('baja', 'Baja', 0.74)],
    reliability: [{ top: 0.001, rows: 50, positives: 8, expected: 6, pred: 0.012, obs: 0.016, obs_lo: 0.008, obs_hi: 0.03 }],
    reading: ['En prueba la calibración esperaba 126,5 entradas a KEV y hubo 93.'],
  },
  baseline: { epss: 0.001, percentile: 0.3, epss_delta: 0, epss_model: 'v2025.03.14', cvss: 7.5, av: 'NETWORK', ac: 'LOW', pr: 'NONE', ui: 'NONE', cwe: 'CWE-79', cna: 'mitre', days_published: 900, edb_exploits: 0, cna_kev_prior: 3 },
  options: { categorical: { cna: ['mitre', 'secure@microsoft.com'], cwe: ['CWE-79'], av: ['NETWORK', 'LOCAL'] }, numeric: {} },
  features: [], how_to_read: { probability: 'Probabilidad calibrada…' },
} as unknown as Setup
const PRED: Prediction = {
  result: { score: 0.8, probability: 0.0123, p_lo: 0.008, p_hi: 0.018, band: 'critica', top: 0.002, lift: 123, base_rate: 0.0001,
    attributions: [{ group: 'EPSS', factor: 3.2, delta_score: 0.2, band_without: 'alta', unused: false }, { group: 'Antigüedad del CVE', factor: 0.5, delta_score: -0.1, band_without: 'critica', unused: false }] },
  case: { cve: 'CVE-2026-1111', snapshot: '2026-08-01', split: 'prueba', label: 1, kev_date: '2026-09-10', days_to_kev: 40 },
  values: { ...SETUP.baseline, epss: 0.9 }, reading: ['Lo que más la sube: EPSS (×3,2).'],
}
const posts: unknown[][] = []
vi.mock('../../lib/api', () => ({
  api: {
    get: (path: string) => Promise.resolve(
      path === '/ml/models' ? [{ id: 'm1', name: 'Random forest', status: 'ready' }]
        : path.endsWith('/ranking') ? { snapshot: '2026-08-01', snapshots: ['2026-07-01', '2026-08-01'], split: 'prueba', hits: 1, positives: 30, rows: [{ cve: 'CVE-2026-1111', score: 0.8, probability: 0.0123, band: 'critica', label: 1 }] }
          : SETUP,
    ),
    post: (...args: unknown[]) => { posts.push(args); return Promise.resolve(PRED) },
  },
}))
vi.mock('sonner', () => ({ toast: { success: () => undefined, error: () => undefined } }))

describe('Laboratorio · Fase 6', () => {
  it('muestra la calibración, predice desde el ranking y explica el resultado', async () => {
    render(<QueryClientProvider client={new QueryClient()}><LabInference datasets={[DS]} /></QueryClientProvider>)
    expect(await screen.findByText('Observado / esperado')).toBeInTheDocument()
    expect(screen.getByText('IC 95 % 0,59 a 0,90 · ideal 1')).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('cell', { name: 'CVE-2026-1111' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]).toEqual(['/ml/models/m1/predict', { cve: 'CVE-2026-1111', snapshot: '2026-08-01' }])
    expect(await screen.findByLabelText('Probabilidad calibrada 1,2 %')).toBeInTheDocument()
    const bars = screen.getByLabelText('Explicación por grupo de variables')
    expect(within(bars).getByText('×3,2')).toBeInTheDocument()
    expect(within(bars).getByText('sin él: Alta')).toBeInTheDocument()
    expect(screen.getByText('Resultado real: entró a KEV el 2026-09-10')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Usar estos valores como escenario' }))
    const epss = screen.getByLabelText('EPSS (0 a 1)')
    expect(epss).toHaveValue(0.9)
    fireEvent.change(epss, { target: { value: '0.05' } })
    fireEvent.change(screen.getByLabelText('CVSS de la CNA'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Predecir' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1][1]).toMatchObject({ values: { epss: 0.05, cvss: null, cna: 'mitre' } })
  })
})
