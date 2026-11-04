import { daysUntil, dueText, slaProgress, formatDate, formatDuration, formatLima, formatPct, limaInputToIso } from './format'
import { hasPermission } from './permissions'
import { ModuleTracker, moduleForPath, type NavigationEvent } from './tracking'

describe('hora de Lima', () => {
  it('muestra un instante UTC en America/Lima (UTC-5)', () => {
    expect(formatLima('2026-11-03T15:30:05Z')).toBe('03/11/2026 10:30:05')
  })
  it('cruza de día correctamente', () => {
    expect(formatLima('2026-11-03T03:00:00Z')).toBe('02/11/2026 22:00:00')
  })
  it('convierte el filtro de Lima a UTC', () => {
    expect(limaInputToIso('2026-11-03T10:30')).toBe('2026-11-03T15:30:00.000Z')
    expect(limaInputToIso('')).toBeUndefined()
  })
  it('formatea duraciones', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(850)).toBe('850 ms')
    expect(formatDuration(65_000)).toBe('1 min 5 s')
  })
})

describe('formato de datos', () => {
  it('porcentajes con coma decimal y guion para ausentes', () => {
    expect(formatPct(0.97312)).toBe('97,3 %')
    expect(formatPct(1, 0)).toBe('100 %')
    expect(formatPct(null)).toBe('—')
  })
  it('fechas dd/mm/aaaa sin desfase de zona', () => {
    expect(formatDate('2026-11-13')).toBe('13/11/2026')
    expect(formatDate(null)).toBe('—')
  })
})

describe('permisos', () => {
  const perms = ['users:view', 'audit:export']
  it('evalúa módulo:acción', () => {
    expect(hasPermission(perms, 'users', 'view')).toBe(true)
    expect(hasPermission(perms, 'users', 'create')).toBe(false)
    expect(hasPermission(perms, 'audit', 'export')).toBe(true)
  })
})

describe('seguimiento de módulos', () => {
  function setup() {
    const events: NavigationEvent[] = []
    let t = 1000
    const tracker = new ModuleTracker((e) => events.push(e), () => t)
    return { events, tracker, tick: (ms: number) => (t += ms) }
  }

  it('registra entrada, y salida con duración al cambiar de ruta', () => {
    const { events, tracker, tick } = setup()
    tracker.go('assets')
    tick(4200)
    tracker.go('users')
    expect(events).toEqual([
      { module: 'assets', event: 'enter' },
      { module: 'assets', event: 'leave', duration_ms: 4200 },
      { module: 'users', event: 'enter' },
    ])
  })

  it('no duplica eventos si la ruta no cambia de módulo', () => {
    const { events, tracker } = setup()
    tracker.go('users')
    tracker.go('users')
    expect(events).toHaveLength(1)
  })

  it('al ocultar o cerrar la pestaña registra la salida; al volver reabre', () => {
    const { events, tracker, tick } = setup()
    tracker.go('audit')
    tick(3000)
    tracker.suspend()
    tracker.suspend() // idempotente
    tick(60_000) // tiempo oculto: no cuenta
    tracker.resume()
    tick(1000)
    tracker.stop()
    expect(events).toEqual([
      { module: 'audit', event: 'enter' },
      { module: 'audit', event: 'leave', duration_ms: 3000 },
      { module: 'audit', event: 'enter' },
      { module: 'audit', event: 'leave', duration_ms: 1000 },
    ])
  })

  it('mapea rutas a módulos', () => {
    expect(moduleForPath('/bitacora')).toBe('audit')
    expect(moduleForPath('/usuarios/123')).toBe('users')
    expect(moduleForPath('/importacion')).toBe('imports')
    expect(moduleForPath('/vulnerabilidades')).toBe('vulnerabilities')
    expect(moduleForPath('/login')).toBeNull()
  })
})

describe('plazos', () => {
  const now = new Date('2026-11-04T15:00:00Z') // 10:00 en Lima
  it('cuenta días enteros desde hoy en Lima', () => {
    expect(daysUntil('2026-11-04', now)).toBe(0)
    expect(daysUntil('2026-11-07', now)).toBe(3)
    expect(daysUntil('2026-11-02', now)).toBe(-2)
    expect(daysUntil(null, now)).toBeNull()
  })
  it('usa el día de Lima y no el de UTC', () => {
    expect(daysUntil('2026-11-04', new Date('2026-11-05T02:00:00Z'))).toBe(0) // 21:00 del 4 en Lima
  })
  it('redacta el plazo', () => {
    expect(dueText(3)).toBe('vence en 3 días')
    expect(dueText(1)).toBe('vence mañana')
    expect(dueText(0)).toBe('vence hoy')
    expect(dueText(-1)).toBe('vencido hace 1 día')
    expect(dueText(-5)).toBe('vencido hace 5 días')
  })
})

describe('avance del SLA', () => {
  it('va de 0 a 1 entre la creación y el vencimiento y se acota', () => {
    const created = '2026-11-01T15:00:00Z'
    const due = '2026-11-05' // vence a las 23:59:59 de Lima
    expect(slaProgress(created, due, new Date('2026-10-31T00:00:00Z').getTime())).toBe(0)
    const mid = slaProgress(created, due, new Date('2026-11-03T15:00:00Z').getTime())
    expect(mid).toBeGreaterThan(0.3)
    expect(mid).toBeLessThan(0.7)
    expect(slaProgress(created, due, new Date('2026-12-01T00:00:00Z').getTime())).toBe(1)
  })
})
