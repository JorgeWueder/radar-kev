export interface NavigationEvent {
  module: string
  event: 'enter' | 'leave'
  duration_ms?: number
}

type Sender = (body: NavigationEvent) => void

/**
 * Reporta entrada y salida de módulo a la bitácora. Lógica pura (reloj y envío inyectados) para poder
 * probarla sin navegador. `suspend`/`resume` cubren el cierre o el ocultamiento de la pestaña.
 */
export class ModuleTracker {
  private current: { module: string; since: number } | null = null
  private suspended = false

  constructor(
    private readonly send: Sender,
    private readonly now: () => number = () => Date.now(),
  ) {}

  /** Cambio de ruta: cierra el módulo anterior (con duración) y abre el nuevo. */
  go(module: string | null): void {
    if (this.current?.module === module) return
    this.leave()
    if (module) {
      this.current = { module, since: this.now() }
      if (!this.suspended) this.send({ module, event: 'enter' })
    }
  }

  private leave(): void {
    if (!this.current) return
    if (!this.suspended) {
      this.send({
        module: this.current.module,
        event: 'leave',
        duration_ms: Math.max(0, this.now() - this.current.since),
      })
    }
    this.current = null
  }

  /** Pestaña oculta o cerrándose: registra la salida con la duración acumulada. */
  suspend(): void {
    if (this.suspended || !this.current) return
    this.send({
      module: this.current.module,
      event: 'leave',
      duration_ms: Math.max(0, this.now() - this.current.since),
    })
    this.suspended = true
  }

  /** La pestaña vuelve a verse: se abre de nuevo el módulo actual. */
  resume(): void {
    if (!this.suspended) return
    this.suspended = false
    if (this.current) {
      this.current.since = this.now()
      this.send({ module: this.current.module, event: 'enter' })
    }
  }

  /** Cierre de sesión: registra la salida del módulo y se detiene. */
  stop(): void {
    this.leave()
  }
}

export const ROUTE_MODULES: Record<string, string> = {
  '/resumen': 'dashboard',
  '/activos': 'assets',
  '/importacion': 'imports',
  '/vulnerabilidades': 'vulnerabilities',
  '/tickets': 'tickets',
  '/alertas': 'alerts',
  '/kev': 'kev',
  '/ejecuciones': 'workflow',
  '/configuracion': 'settings',
  '/usuarios': 'users',
  '/roles': 'roles',
  '/bitacora': 'audit',
  '/perfil': 'app',
}

export function moduleForPath(pathname: string): string | null {
  const key = Object.keys(ROUTE_MODULES).find((p) => pathname === p || pathname.startsWith(`${p}/`))
  return key ? ROUTE_MODULES[key] : null
}
