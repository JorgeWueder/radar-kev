import { afterEach, vi } from 'vitest'

import { ApiError, errorMessage, request, setAccessToken, upload } from './api'
import { criticalityKind } from './labels'
import { loginErrorMessage } from '../pages/Login'

afterEach(() => {
  vi.restoreAllMocks()
  setAccessToken(null)
})

describe('errorMessage', () => {
  it('extrae el detalle de texto y el primer error de validación', () => {
    expect(errorMessage({ detail: 'Sesión expirada' }, 'x')).toBe('Sesión expirada')
    expect(errorMessage({ detail: [{ msg: 'Campo requerido' }] }, 'x')).toBe('Campo requerido')
    expect(errorMessage(null, 'respaldo')).toBe('respaldo')
  })
})

describe('mensajes de login', () => {
  it('distingue bloqueo, límite de intentos y credenciales', () => {
    expect(loginErrorMessage(new ApiError(423, ''))).toMatch(/bloqueada/)
    expect(loginErrorMessage(new ApiError(429, ''))).toMatch(/Demasiados/)
    expect(loginErrorMessage(new ApiError(401, ''))).toBe('Credenciales inválidas.')
    expect(loginErrorMessage(new Error('red'))).toMatch(/conexión/)
  })
})

describe('cliente HTTP', () => {
  it('renueva el token una vez ante un 401 y reintenta', async () => {
    setAccessToken('viejo')
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`)
      if (url.endsWith('/auth/refresh')) return new Response(JSON.stringify({ access_token: 'nuevo' }), { status: 200 })
      const auth = (init?.headers as Record<string, string>)?.Authorization
      return auth === 'Bearer nuevo' ? new Response(JSON.stringify({ ok: true }), { status: 200 }) : new Response('{}', { status: 401 })
    }))
    expect(await request<{ ok: boolean }>('/assets')).toEqual({ ok: true })
    expect(calls).toEqual(['GET /api/v1/assets', 'POST /api/v1/auth/refresh', 'GET /api/v1/assets'])
  })

  it('sube archivos como multipart sin forzar Content-Type', async () => {
    let init: RequestInit | undefined
    vi.stubGlobal('fetch', vi.fn(async (_u: string, i?: RequestInit) => { init = i; return new Response('{}', { status: 201 }) }))
    await upload('/imports/preview', new File(['a,b'], 'x.csv'))
    expect(init?.body).toBeInstanceOf(FormData)
    expect((init?.headers as Record<string, string>)['Content-Type']).toBeUndefined()
  })

  it('traduce errores HTTP a ApiError con el mensaje del servidor', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Archivo no permitido' }), { status: 422 })))
    await expect(request('/imports/preview', { method: 'POST', body: {} })).rejects.toMatchObject({ status: 422, message: 'Archivo no permitido' })
  })
})

describe('criticidad', () => {
  it('mapea a un tono (el texto siempre acompaña)', () => {
    expect(criticalityKind(4)).toBe('danger')
    expect(criticalityKind(3)).toBe('warn')
    expect(criticalityKind(1)).toBe('neutral')
  })
})

describe('etiquetas de tickets', () => {
  it('cubren todos los estados, prioridades y SLA que envía el backend', async () => {
    const { PRIORITY, SLA, TICKET_STATUS, BAND } = await import('./labels')
    for (const s of ['open', 'in_progress', 'resolved', 'closed', 'risk_accepted']) expect(TICKET_STATUS[s]).toBeDefined()
    for (const p of ['critical', 'high', 'medium', 'low']) { expect(PRIORITY[p]).toBeDefined(); expect(BAND[p]).toBeDefined() }
    for (const s of ['vencido', 'por_vencer', 'en_plazo', 'no_aplica']) expect(SLA[s]).toBeDefined()
  })
})
