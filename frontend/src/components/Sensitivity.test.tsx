import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import { SensitivityPanel, type SensitivityResult } from './Sensitivity'

const cur = { trial: 0, w_epss: 0.35, w_percentile: 0.15, w_cvss: 0.25, w_asset: 0.25, spearman: 1, top_overlap: 10, band_changes: 0, auc: 0.946, current: true }
const other = { ...cur, trial: 3, w_epss: 0.5, w_percentile: 0.1, w_cvss: 0.3, w_asset: 0.1, spearman: 0.97, top_overlap: 9, band_changes: 2, auc: 1, current: false }
const RESULT: SensitivityResult = {
  n_findings: 39, top_k: 10, elapsed_ms: 250, trials: [cur, other], current: cur, best: [other],
  importance: [{ weight: 'w_percentile', label: 'Percentil EPSS', pct: 43.8 }, { weight: 'w_cvss', label: 'CVSS', pct: 3.5 }],
  interpretation: ['La prioridad casi no depende de los pesos: KEV (el piso del score) ordena lo urgente.'],
  how_to_read: { trials: 't', importance: 'i', best: 'b' },
}

const sent: unknown[] = []
vi.mock('../lib/api', () => ({ api: { post: (_: string, body: unknown) => { sent.push(body); return Promise.resolve(RESULT) } } }))

class RO { observe() {} unobserve() {} disconnect() {} }

describe('SensitivityPanel', () => {
  beforeAll(() => { globalThis.ResizeObserver = RO as unknown as typeof ResizeObserver })

  it('envía la configuración de la búsqueda y muestra la vigente, la importancia y la lectura', async () => {
    render(<QueryClientProvider client={new QueryClient()}><SensitivityPanel /></QueryClientProvider>)
    fireEvent.click(screen.getByRole('button', { name: '500' }))
    fireEvent.click(screen.getByRole('button', { name: 'Ejecutar análisis' }))
    expect(await screen.findByText(/KEV \(el piso del score\) ordena lo urgente/)).toBeInTheDocument()
    expect(sent[0]).toMatchObject({ n_trials: 500, seed: 7, bounds: { w_epss: [0, 1] } })
    const row = screen.getAllByRole('row').find((r) => r.textContent?.startsWith('Vigente'))
    expect(row).toHaveTextContent('Vigente0,350,150,250,251,0010/1000,95')
    expect(screen.getByText('Percentil EPSS').closest('li')).toHaveTextContent('44 %')
  })
})
