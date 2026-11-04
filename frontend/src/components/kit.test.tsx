import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'

import { SlaBar } from './detail'
import { DataTable, DetailDrawer, KpiCard, Meta, Pagination, rowOpen, Tabs } from './kit'

describe('Meta', () => {
  it('es gris por defecto y solo en alerta se pone rojo', () => {
    render(
      <>
        <Meta>Normal</Meta>
        <Meta alert>Vencido</Meta>
      </>,
    )
    expect(screen.getByText('Normal').className).toContain('text-muted')
    expect(screen.getByText('Vencido').className).toContain('text-danger')
  })
})

describe('DataTable', () => {
  const cols = [{ key: 'n', header: 'Nombre', cell: (r: { n: string }) => r.n }]
  it('muestra skeleton al cargar, vacío sin filas y filas con header', () => {
    const { rerender } = render(<DataTable columns={cols} rows={undefined} rowKey={(r) => r.n} loading empty={<p>Vacío</p>} />)
    expect(screen.getByRole('status', { name: 'Cargando' })).toBeInTheDocument()
    rerender(<DataTable columns={cols} rows={[]} rowKey={(r) => r.n} empty={<p>Vacío</p>} />)
    expect(screen.getByText('Vacío')).toBeInTheDocument()
    rerender(<DataTable columns={cols} rows={[{ n: 'a' }]} rowKey={(r) => r.n} empty={<p>Vacío</p>} />)
    expect(screen.getByRole('columnheader', { name: 'Nombre' }).className).toContain('sticky')
    expect(screen.getByText('a')).toBeInTheDocument()
  })
})

describe('Pagination', () => {
  it('no aparece con una sola página y navega con Anterior/Siguiente', () => {
    const onPage = vi.fn()
    const { rerender } = render(<Pagination page={0} total={10} pageSize={50} onPage={onPage} />)
    expect(screen.queryByText('Siguiente')).toBeNull()
    rerender(<Pagination page={0} total={120} pageSize={50} onPage={onPage} />)
    expect(screen.getByText('1–50 de 120')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Siguiente'))
    expect(onPage).toHaveBeenCalledWith(1)
    expect(screen.getByText('Anterior')).toBeDisabled()
  })
})

describe('KpiCard', () => {
  it('enlaza a su lista filtrada cuando recibe `to`', () => {
    render(
      <MemoryRouter>
        <KpiCard label="En KEV" value={7} to="/vulnerabilidades?kev=1" hero />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link')).toHaveAttribute('href', '/vulnerabilidades?kev=1')
  })
})

describe('DetailDrawer', () => {
  function Harness() {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button onClick={() => setOpen(true)}>Abrir</button>
        <DetailDrawer open={open} onClose={() => setOpen(false)} title="CVE-2024-3400">
          <p>Contenido</p>
        </DetailDrawer>
      </>
    )
  }
  it('abre como diálogo, se cierra con Escape y devuelve el foco', async () => {
    render(<Harness />)
    const opener = screen.getByText('Abrir')
    opener.focus()
    fireEvent.click(opener)
    expect(await screen.findByRole('dialog', { name: 'CVE-2024-3400' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(opener)
  })
})

describe('rowOpen', () => {
  it('abre con clic y con Enter, pero no con teclas de controles internos', () => {
    const open = vi.fn()
    render(
      <table>
        <tbody>
          <tr {...rowOpen(open)} data-testid="fila">
            <td>
              <input aria-label="interno" />
            </td>
          </tr>
        </tbody>
      </table>,
    )
    const row = screen.getByTestId('fila')
    fireEvent.click(row)
    fireEvent.keyDown(row, { key: 'Enter' })
    expect(open).toHaveBeenCalledTimes(2)
    fireEvent.keyDown(screen.getByLabelText('interno'), { key: 'Enter' })
    expect(open).toHaveBeenCalledTimes(2)
  })
})

describe('SlaBar', () => {
  it('es gris en plazo, roja solo vencida y dice sin plazo cuando no aplica', () => {
    const created = '2026-10-01T00:00:00Z'
    const { container, rerender } = render(<SlaBar created={created} due="2099-01-01" state="en_plazo" />)
    expect(container.querySelector('.bg-muted')).not.toBeNull()
    expect(container.querySelector('.bg-danger')).toBeNull()
    rerender(<SlaBar created={created} due="2026-10-05" state="vencido" />)
    expect(container.querySelector('.bg-danger')).not.toBeNull()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
    rerender(<SlaBar created={created} due={null} state="no_aplica" />)
    expect(screen.getByText('Sin plazo')).toBeInTheDocument()
  })
})

describe('Tabs', () => {
  it('marca la pestaña activa y cambia con clic y con las flechas', () => {
    const onChange = vi.fn()
    render(<Tabs label="Secciones" value="a" onChange={onChange} tabs={[{ id: 'a', label: 'Uno' }, { id: 'b', label: 'Dos' }]} />)
    expect(screen.getByRole('tab', { name: 'Uno' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: 'Dos' }))
    expect(onChange).toHaveBeenLastCalledWith('b')
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowRight' })
    expect(onChange).toHaveBeenLastCalledWith('b')
    fireEvent.keyDown(screen.getByRole('tablist'), { key: 'ArrowLeft' })
    expect(onChange).toHaveBeenLastCalledWith('b') // desde la primera, la anterior es la última
  })
})
