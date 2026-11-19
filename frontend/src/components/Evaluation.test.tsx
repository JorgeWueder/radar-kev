import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'

import { type Evaluation, EvaluationPanel } from './Evaluation'

const DATA: Evaluation = {
  n: 12, positives: 6, negatives: 6, prevalence: 50, reliable: true,
  interpretation: ['El criterio que mejor separa lo explotado es EPSS: AUC 1,00.'],
  how_to_read: { roc: 'roc', pr: 'pr', rules: 'reglas' },
  predictors: [
    { key: 'cvss', label: 'CVSS', auc: 0.3, auc_ci: [0.1, 0.6], ap: 0.4, roc: [{ fpr: 0, tpr: 0 }, { fpr: 1, tpr: 1 }], pr: [{ recall: 1, precision: 0.5 }] },
    { key: 'epss', label: 'EPSS', auc: 1, auc_ci: [1, 1], ap: 1, roc: [{ fpr: 0, tpr: 0 }, { fpr: 0, tpr: 1 }], pr: [{ recall: 1, precision: 1 }] },
  ],
  rules: [{ key: 'cvss_7', label: 'CVSS ≥ 7 (alto y crítico)', tp: 3, fp: 6, fn: 3, tn: 0, coverage: 50, efficiency: 33.3, effort: 75 }],
}

vi.mock('../lib/api', () => ({ api: { get: () => Promise.resolve(DATA) } }))

class RO { observe() {} unobserve() {} disconnect() {} }

describe('EvaluationPanel', () => {
  beforeAll(() => { globalThis.ResizeObserver = RO as unknown as typeof ResizeObserver })

  it('ordena los criterios por AUC, muestra la lectura y la matriz de cada regla', async () => {
    render(<QueryClientProvider client={new QueryClient()}><EvaluationPanel /></QueryClientProvider>)
    expect(await screen.findByText(/mejor separa lo explotado es EPSS/)).toBeInTheDocument()
    const rows = screen.getAllByRole('row').map((r) => r.textContent ?? '')
    expect(rows.findIndex((t) => t.startsWith('EPSS'))).toBeLessThan(rows.findIndex((t) => t.startsWith('CVSS1') || t.startsWith('CVSS0')))
    const card = screen.getByText('CVSS ≥ 7 (alto y crítico)').closest('li')
    expect(card).toHaveTextContent('Cobertura50 %Precisión33 %Esfuerzo75 %')
    expect(screen.getByRole('table', { name: /Matriz de confusión: CVSS ≥ 7/ })).toHaveTextContent('Marcados36Sin marcar30')
    expect(screen.getByRole('figure', { name: /Curva ROC.*EPSS: AUC 1/ })).toBeInTheDocument()
  })
})
