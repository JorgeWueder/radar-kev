import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { Dialog, rowToggle, StatusBadge } from './ui'

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}>Abrir</button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Nuevo usuario">
        <input aria-label="Nombre" />
        <button>Guardar</button>
      </Dialog>
    </>
  )
}

describe('Dialog accesible', () => {
  it('mueve el foco adentro, atrapa Tab y cierra con Escape devolviendo el foco', async () => {
    render(<Harness />)
    const opener = screen.getByText('Abrir')
    opener.focus()
    fireEvent.click(opener)
    const name = await screen.findByLabelText('Nombre')
    expect(screen.getByRole('dialog', { name: 'Nuevo usuario' })).toBeInTheDocument()
    expect(document.activeElement).toBe(name) // el foco entra al diálogo

    const save = screen.getByText('Guardar')
    save.focus()
    fireEvent.keyDown(document, { key: 'Tab' }) // desde el último elemento vuelve al primero
    expect(document.activeElement).toBe(name)
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true }) // y hacia atrás, al último
    expect(document.activeElement).toBe(save)

    fireEvent.keyDown(document, { key: 'Escape' })
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(opener) // el foco vuelve a quien lo abrió
  })
})

describe('rowToggle', () => {
  it('hace que una fila se pueda alcanzar y accionar con el teclado', () => {
    const toggle = vi.fn()
    const props = rowToggle(false, toggle)
    expect(props.tabIndex).toBe(0)
    expect(props['aria-expanded']).toBe(false)
    const prevent = vi.fn()
    props.onKeyDown({ key: 'Enter', preventDefault: prevent } as never)
    props.onKeyDown({ key: ' ', preventDefault: prevent } as never)
    props.onKeyDown({ key: 'a', preventDefault: prevent } as never)
    expect(toggle).toHaveBeenCalledTimes(2) // Enter y Espacio; otras teclas no
  })
})

describe('StatusBadge', () => {
  it('nunca depende solo del color: lleva texto', () => {
    render(<StatusBadge kind="danger">Vencido</StatusBadge>)
    expect(screen.getByText('Vencido')).toBeInTheDocument()
  })
})
