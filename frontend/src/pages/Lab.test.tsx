import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import type { Dataset, Job, Profile } from '../components/lab/types'
import { JobProgress } from '../components/lab/JobProgress'
import Lab from './Lab'

const DS: Dataset = {
  id: 'd1', name: 'KEV en 90 días', description: 'Fotos 2025', notes: '', tags: ['tesis'], status: 'ready', created_at: '2026-11-19T20:00:00Z', updated_at: '2026-11-19T20:00:00Z',
  params: { start: '2025-01-01', until: '2026-11-18', horizon_days: 90, neg_rate: 0.05, seed: 7, snapshots: 20, split: 'temporal 70/15/15' },
  sources: [{ kind: 'nvd', name: 'NIST NVD (feeds CVE 2.0)', license: 'Datos públicos', url: 'u', file: 'nvd_2024.json.gz', bytes: 25_177_078, sha256: 'abcdef0123456789' }],
  stats: { rows: 312_000, positives: 480 },
  features: [{ name: 'epss', type: 'num', source: 'EPSS', description: 'Probabilidad EPSS' }],
}
const PROFILE: Profile = {
  overview: { rows: 312_000, positives: 480, negatives_sampled: 311_520, neg_rate: 0.05, universe_estimate: 6_230_880, prevalence_pct: 0.0077, snapshots: 20, cves: 330_000 },
  snapshots: [{ snapshot: '2025-01-01', split: 'desarrollo', rows: 15_000, positives: 25, prevalence_pct: 0.008, epss_model: 'v2025.03.14' }],
  splits: [{ split: 'desarrollo', label: 'Desarrollo (70 %)', rows: 220_000, positives: 330, snapshots: 14, from: '2025-01-01', to: '2026-02-01', share_pct: 70, prevalence_pct: 0.0075 }],
  numeric: [{ name: 'epss', description: 'Probabilidad EPSS', missing_pct: 0, median_pos: 0.0083, median_neg: 0.0004, p75_pos: 0.1, p75_neg: 0.001, auc: 0.6, hist: [{ label: '0 a 0,001', neg: 100, pos: 2 }] }],
  categorical: [{ name: 'ssvc_exploitation', description: 'SSVC', cardinality: 4, top: [{ value: 'active', rows: 50, positives: 20, prevalence_pct: 40, small: false }] }],
  checks: [{ key: 'temporal', label: 'Orden temporal de la partición', status: 'ok', detail: 'Desarrollo es anterior a validación.' }],
  interpretation: ['Un problema muy desbalanceado, por eso la métrica principal será PR-AUC.'],
  how_to_read: { splits: 's', numeric: 'n', categorical: 'c', checks: 'k' },
}
const JOB: Job = { id: 'j1', kind: 'dataset', status: 'running', progress: 42, message: 'Foto 2025-06-01 (6 de 20)', log: [{ t: '2026-11-19T20:01:00Z', pct: 42, msg: 'Foto 2025-06-01 (6 de 20)' }], target_id: 'd1', started_at: '2026-11-19T20:00:00Z', finished_at: null }

vi.mock('../lib/api', () => ({
  api: {
    get: (path: string) => Promise.resolve(
      path === '/ml/datasets' ? [DS] : path === '/ml/jobs' ? [] : path === '/ml/datasets/d1' ? DS : path === '/ml/datasets/d1/profile' ? PROFILE : path === '/ml/jobs/j1' ? JOB : [],
    ),
    post: () => Promise.resolve({ dataset_id: 'd2', job_id: 'j1' }),
    patch: () => Promise.resolve(DS),
  },
}))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ can: () => true }) }))

const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('Laboratorio · Fase 1', () => {
  it('lista los datasets, abre el primero listo con su resumen y su metadata', async () => {
    wrap(<Lab />)
    expect(await screen.findByText(/métrica principal será PR-AUC/)).toBeInTheDocument()
    expect(screen.getByText('Desarrollo (70 %)')).toBeInTheDocument()
    expect(screen.getByText('6 230 880')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Validación' }))
    expect(screen.getByText(/Desarrollo es anterior a validación/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Metadata' }))
    expect(screen.getByDisplayValue('KEV en 90 días')).toBeInTheDocument()
    expect(screen.getByText('abcdef012345…')).toBeInTheDocument()
    expect(screen.getByText('Probabilidad EPSS')).toBeInTheDocument()
  })

  it('el monitoreo muestra el avance del trabajo', async () => {
    wrap(<JobProgress jobId="j1" />)
    expect(await screen.findByRole('progressbar', { name: 'Avance del trabajo' })).toHaveAttribute('aria-valuenow', '42')
    expect(screen.getAllByText(/Foto 2025-06-01 \(6 de 20\)/).length).toBeGreaterThan(0)
  })
})
