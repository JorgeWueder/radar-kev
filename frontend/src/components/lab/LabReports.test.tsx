import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { LabReports } from './LabReports'
import type { Dataset } from './types'

const DS = { id: 'd2', name: 'KEV en 90 días v2', status: 'ready', tags: [], params: {}, stats: {} } as unknown as Dataset
const calls: unknown[][] = []

vi.mock('../../lib/api', () => ({
  api: { get: () => Promise.resolve([{ id: 'm1', name: 'Random forest', status: 'ready' }]) },
  download: (...args: unknown[]) => { calls.push(args); return Promise.resolve() },
}))
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ can: () => true }) }))
vi.mock('sonner', () => ({ toast: { success: () => undefined, error: () => undefined } }))

describe('Laboratorio · Fase 5', () => {
  it('pide cada reporte con su dataset, modelo y punto de operación', async () => {
    render(<QueryClientProvider client={new QueryClient()}><LabReports datasets={[DS]} /></QueryClientProvider>)
    await screen.findByRole('option', { name: 'Random forest' })
    fireEvent.click(screen.getByRole('button', { name: 'Revisar el 5 %' }))
    fireEvent.click(screen.getByRole('button', { name: 'Evaluación en PDF' }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual(['/reports/ml_evaluation', { fmt: 'pdf', dataset_id: 'd2', op: 5 }, 'radar_ml_evaluation.pdf', 'POST'])
    await waitFor(() => expect(screen.getByRole('button', { name: 'Explicabilidad en Word' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Explicabilidad en Word' }))
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1]).toEqual(['/reports/ml_explain', { fmt: 'docx', model_id: 'm1' }, 'radar_ml_explain.docx', 'POST'])
  })
})
