import { render, screen } from '@testing-library/react'

import { AiBadge } from './AiBadge'

describe('AiBadge', () => {
  it('marca visiblemente el contenido generado por IA, con el modelo si se conoce', () => {
    render(<AiBadge model="qwen2.5:3b" />)
    expect(screen.getByText(/Generado por IA · qwen2\.5:3b/)).toBeInTheDocument()
  })
  it('funciona sin modelo', () => {
    render(<AiBadge />)
    expect(screen.getByText('Generado por IA')).toBeInTheDocument()
  })
})
