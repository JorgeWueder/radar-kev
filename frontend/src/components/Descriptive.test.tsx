import { describe, expect, it } from 'vitest'

import { num } from './Descriptive'

describe('num', () => {
  it('usa coma decimal, quita ",0" y marca la ausencia de dato', () => {
    expect(num(12.5)).toBe('12,5')
    expect(num(10)).toBe('10')
    expect(num(0.4, '%')).toBe('0,4 %')
    expect(num(33.33, '%', 0)).toBe('33 %')
    expect(num(null)).toBe('—')
  })
})
