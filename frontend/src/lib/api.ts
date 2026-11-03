const BASE = '/api/v1'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let accessToken: string | null = null
let onAuthLost: () => void = () => {}
let refreshing: Promise<string | null> | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}
export function getAccessToken(): string | null {
  return accessToken
}
export function setAuthLostHandler(fn: () => void): void {
  onAuthLost = fn
}

export function errorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string }
    if (first?.msg) return first.msg
  }
  return fallback
}

/** Renueva el access token con la cookie httpOnly. Una sola renovación en vuelo a la vez. */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) return null
        const data = (await r.json()) as { access_token: string }
        accessToken = data.access_token
        return accessToken
      })
      .catch(() => null)
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

interface Options {
  method?: string
  body?: unknown
  params?: Record<string, string | number | undefined | null>
  raw?: boolean
}

function buildUrl(path: string, params?: Options['params']): string {
  const url = `${BASE}${path}`
  if (!params) return url
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
  }
  const s = qs.toString()
  return s ? `${url}?${s}` : url
}

async function send(path: string, opts: Options): Promise<Response> {
  const headers: Record<string, string> = {}
  if (opts.body !== undefined && !(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  return fetch(buildUrl(path, opts.params), {
    method: opts.method ?? 'GET',
    headers,
    credentials: 'include',
    body:
      opts.body === undefined ? undefined : opts.body instanceof FormData ? opts.body : JSON.stringify(opts.body),
  })
}

export async function request<T>(path: string, opts: Options = {}): Promise<T> {
  let res = await send(path, opts)
  if (res.status === 401 && !path.startsWith('/auth/')) {
    const token = await refreshAccessToken()
    if (token) res = await send(path, opts)
    else onAuthLost()
  }
  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      /* respuesta sin cuerpo JSON */
    }
    throw new ApiError(res.status, errorMessage(body, 'No se pudo completar la operación'))
  }
  if (opts.raw) return res as unknown as T
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string, params?: Options['params']) => request<T>(path, { params }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

/** Sube un archivo (multipart) en el campo `file`. */
export function upload<T>(path: string, file: File): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  return request<T>(path, { method: 'POST', body: form })
}

/** Descarga un archivo autenticado (exportaciones) y lo entrega al navegador. */
export async function download(
  path: string,
  params: Options['params'],
  filename: string,
): Promise<void> {
  const res = await request<Response>(path, { params, raw: true })
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Envío que sobrevive al cierre de la pestaña (keepalive); no reintenta ni lanza. */
export function sendKeepalive(path: string, body: unknown): void {
  try {
    void fetch(`${BASE}${path}`, {
      method: 'POST',
      keepalive: true,
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify(body),
    })
  } catch {
    /* sin red: el evento se pierde, no se bloquea la salida */
  }
}
