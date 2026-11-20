import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'

import { type Explanation, LabExplain } from './LabExplain'
import type { Dataset } from './types'

const DS = { id: 'd2', name: 'KEV en 90 días v2', status: 'ready', tags: [], params: {}, stats: {} } as unknown as Dataset
const caseOf = (cve: string, label: number) => ({
  cve, snapshot: '2026-07-01', label, prob: 0.42, values: { epss: 0.91, cvss: 9.8, days_published: 12, cna: 'secure@microsoft.com', cwe: 'CWE-787', edb_exploits: 1 },
  attributions: [{ group: 'EPSS', delta: 0.2 }, { group: 'Antigüedad del CVE', delta: -0.05 }],
})
const R: Explanation = {
  model: { id: 'm1', name: 'Random forest', algorithm: 'random_forest' }, drop: [],
  importance: { base_roc_auc: 0.91, rows: [{ name: 'EPSS', kind: 'grupo', mean: 0.08, sd: 0.01 }, { name: 'days_published', kind: 'variable', mean: 0.05, sd: 0.004 }] },
  pdp: [{ feature: 'epss', points: [{ x: 0.001, y: 0.001 }, { x: 0.9, y: 0.02 }] }],
  pdp2d: { x: 'epss', y: 'days_published', xs: [0.001, 0.5], ys: [10, 900], cells: [{ x: 0.001, y: 10, p: 0.001 }, { x: 0.5, y: 10, p: 0.02 }, { x: 0.001, y: 900, p: 0.0005 }, { x: 0.5, y: 900, p: 0.004 }] },
  local: { aciertos: [caseOf('CVE-2026-1111', 1)], escapados: [caseOf('CVE-2026-2222', 1)], falsas_alarmas: [caseOf('CVE-2026-3333', 0)] },
  coefficients: [],
  equivalences: [{ promptuario: 'Grad-CAM++', aqui: 'Atribución por oclusión', porque: 'Mide cuánto cambia la probabilidad al tapar cada grupo.' }],
  interpretation: ['Los grupos de variables en los que más se apoya el modelo: EPSS (0,080).'], how_to_read: {},
}

vi.mock('../../lib/api', () => ({
  api: { get: (path: string) => Promise.resolve(path === '/ml/models' ? [{ id: 'm1', name: 'Random forest', status: 'ready' }] : R) },
}))
class RO { observe() {} unobserve() {} disconnect() {} }

describe('Laboratorio · Fase 4', () => {
  beforeAll(() => { globalThis.ResizeObserver = RO as unknown as typeof ResizeObserver })

  it('muestra equivalencias, importancia, mapa 2D y explicaciones por caso', async () => {
    render(<QueryClientProvider client={new QueryClient()}><LabExplain datasets={[DS]} /></QueryClientProvider>)
    expect(await screen.findByText('Grad-CAM++')).toBeInTheDocument()
    expect(screen.getByText('Atribución por oclusión')).toBeInTheDocument()
    expect(screen.getByRole('figure', { name: /Mapa de interacción entre EPSS y Días desde la publicación/ })).toBeInTheDocument()
    expect(screen.getByLabelText('Atribución por oclusión de CVE-2026-1111')).toHaveTextContent('+20 pp')
    fireEvent.click(screen.getByRole('tab', { name: 'KEV que se escaparon' }))
    expect(screen.getByText('CVE-2026-2222')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Por variable' }))
    expect(screen.getByTitle('days_published')).toHaveTextContent('Días desde la publicación') // la barra de la variable
  })
})
