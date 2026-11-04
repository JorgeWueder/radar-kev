import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { ApiError } from '../lib/api'
import Login from './Login'

// Función simple (no vi.fn): vitest deja sin atender el rechazo que registra internamente para sus espías.
let impl: () => Promise<void> = () => Promise.resolve()
const login = () => impl()
vi.mock('../lib/auth', () => ({ useAuth: () => ({ user: null, login }) }))

function setup() {
  render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>,
  )
}

describe('Login', () => {
  beforeEach(() => {
    impl = () => Promise.resolve()
  })

  it('usa los autocomplete correctos y alterna mostrar/ocultar contraseña', () => {
    setup()
    expect(screen.getByLabelText('Correo')).toHaveAttribute('autocomplete', 'username')
    const pw = screen.getByLabelText('Contraseña')
    expect(pw).toHaveAttribute('autocomplete', 'current-password')
    expect(pw).toHaveAttribute('type', 'password')
    fireEvent.click(screen.getByRole('button', { name: 'Mostrar contraseña' }))
    expect(pw).toHaveAttribute('type', 'text')
    expect(screen.getByRole('button', { name: 'Ocultar contraseña' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('avisa del Bloq Mayús y lo oculta al salir del campo', () => {
    setup()
    const pw = screen.getByLabelText('Contraseña')
    fireEvent.keyUp(pw, { key: 'A', modifierCapsLock: true })
    expect(screen.getByText('Bloq Mayús está activado')).toBeInTheDocument()
    fireEvent.blur(pw)
    expect(screen.queryByText('Bloq Mayús está activado')).toBeNull()
  })

  it('muestra un error genérico y no revela si el correo existe', async () => {
    impl = () => Promise.reject(new ApiError(401, 'Credenciales inválidas'))
    setup()
    fireEvent.change(screen.getByLabelText('Correo'), { target: { value: 'nadie@radar.local' } })
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Correo o contraseña incorrectos.')
  })

  it('distingue la cuenta bloqueada y deja el botón en estado de carga mientras envía', async () => {
    let reject: (e: Error) => void = () => undefined
    impl = () => new Promise<void>((_, r) => (reject = r))
    setup()
    fireEvent.change(screen.getByLabelText('Correo'), { target: { value: 'a@radar.local' } })
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ingresar' }))
    const busy = await screen.findByRole('button', { name: /Ingresando/ })
    expect(busy).toBeDisabled()
    reject(new ApiError(423, ''))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/bloqueada/))
  })
})
