import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { type Check, num, QualityBlock } from './Descriptive'

describe('num', () => {
  it('usa coma decimal, quita ",0" y marca la ausencia de dato', () => {
    expect(num(12.5)).toBe('12,5')
    expect(num(10)).toBe('10')
    expect(num(0.4, '%')).toBe('0,4 %')
    expect(num(33.33, '%', 0)).toBe('33 %')
    expect(num(null)).toBe('—')
  })
})

describe('QualityBlock', () => {
  const checks: Check[] = [
    { key: 'assumed_criticality', label: 'Criticidad supuesta', status: 'warn', count: 3, detail: '3 hallazgos en activos por completar.' },
    { key: 'missing_cvss', label: 'Sin CVSS', status: 'ok', count: null, detail: 'Todos los hallazgos tienen CVSS.' },
  ]

  it('muestra los avisos con icono, texto y enlace para corregir, y pliega lo correcto', () => {
    render(<MemoryRouter><QualityBlock q={{ status: 'warn', checks, interpretation: ['1 aviso antes de leer las cifras.'] }} /></MemoryRouter>)
    expect(screen.getByRole('region', { name: 'Calidad de los datos' })).toBeInTheDocument()
    expect(screen.getByLabelText('Aviso')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Completar activos' })).toHaveAttribute('href', '/activos')
    expect(screen.getByText('1 validación correcta o informativa')).toBeInTheDocument()
  })

  it('no muestra nada si no hay validaciones', () => {
    const { container } = render(<QualityBlock q={{ status: 'ok', checks: [], interpretation: [] }} />)
    expect(container).toBeEmptyDOMElement()
  })
})
