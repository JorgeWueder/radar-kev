import { applyTheme, resolveTheme } from './theme'

describe('tema', () => {
  it('respeta la preferencia guardada', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })
  it('cae al esquema del sistema si no hay valor válido', () => {
    expect(resolveTheme(null, true)).toBe('dark')
    expect(resolveTheme('otro', false)).toBe('light')
  })
  it('applyTheme alterna la clase dark', () => {
    applyTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    applyTheme('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })
})
