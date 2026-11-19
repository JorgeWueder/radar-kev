import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'

import { UniversePanel, type UniverseResult } from './Universe'

const RESULT: UniverseResult = {
  as_of: '2026-08-20', until: '2026-11-18', horizon_days: 90, n: 361208, excluded_known: 1673, positives: 40, not_scored: 73,
  auc: 0.596, auc_ci: [0.504, 0.689], model_version: 'v2026.06.15', computed_at: '2026-11-19T20:30:00Z',
  interpretation: ['EPSS anticipó esas entradas con un AUC de 0,60.'], how_to_read: { effort: 'e', rules: 'r' },
  effort: [{ share_pct: 1, cves: 3613, captured: 4, coverage_pct: 10, precision_pct: 0.111, lift: 10 }],
  rules: [{ threshold_pct: 10, marked: 16031, effort_pct: 4.44, captured: 9, coverage_pct: 22.5, precision_pct: 0.056 }],
}

let data: UniverseResult | null = RESULT
let allowed = true
vi.mock('../lib/api', () => ({ api: { get: () => Promise.resolve(data), post: () => Promise.resolve(data) } }))
vi.mock('../lib/auth', () => ({ useAuth: () => ({ can: () => allowed }) }))

const setup = () => render(<QueryClientProvider client={new QueryClient()}><UniversePanel /></QueryClientProvider>)

describe('UniversePanel', () => {
  it('muestra el resultado con miles separados, AUC con su intervalo y las tablas', async () => {
    data = RESULT
    allowed = true
    setup()
    expect(await screen.findByText('361 208')).toBeInTheDocument()
    expect(screen.getByText('0,60')).toBeInTheDocument()
    expect(screen.getByText(/0,50 a 0,69/)).toBeInTheDocument()
    expect(screen.getByText('EPSS ≥ 10 %').closest('tr')).toHaveTextContent('16 0314,4 %9 (23 %)')
    expect(screen.getByRole('button', { name: 'Calcular' })).toBeInTheDocument()
  })

  it('sin resultado ni permiso, explica a quién pedirlo y no muestra el botón', async () => {
    data = null
    allowed = false
    setup()
    expect(await screen.findByText(/Pida a un analista/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Calcular' })).not.toBeInTheDocument()
  })
})
