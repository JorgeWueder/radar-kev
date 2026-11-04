import {
  ArrowsClockwise,
  Bell,
  Bug,
  ClipboardText,
  Crosshair,
  Gauge,
  HardDrives,
  Moon,
  ShieldCheck,
  SlidersHorizontal,
  Sparkle,
  Target,
  Ticket,
  SignOut,
  Sun,
  UploadSimple,
  UserCircle,
  Users,
} from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ComponentType } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { api, sendKeepalive } from '../lib/api'
import { useAuth } from '../lib/auth'
import { applyTheme } from '../lib/theme'
import { ModuleTracker, moduleForPath } from '../lib/tracking'
import type { Action } from '../lib/permissions'

interface NavItem {
  to: string
  label: string
  icon: ComponentType<{ size?: number; weight?: 'regular' }>
  module: string
  action: Action
}

const NAV: NavItem[] = [
  { to: '/resumen', label: 'Resumen', icon: Gauge, module: 'dashboard', action: 'view' },
  { to: '/asistente', label: 'Asistente IA', icon: Sparkle, module: 'ai', action: 'view' },
  { to: '/alertas', label: 'Alertas', icon: Bell, module: 'alerts', action: 'view' },
  { to: '/tickets', label: 'Tickets', icon: Ticket, module: 'tickets', action: 'view' },
  { to: '/activos', label: 'Activos', icon: HardDrives, module: 'assets', action: 'view' },
  { to: '/importacion', label: 'Importación', icon: UploadSimple, module: 'imports', action: 'view' },
  { to: '/vulnerabilidades', label: 'Vulnerabilidades', icon: Bug, module: 'vulnerabilities', action: 'view' },
  { to: '/kev', label: 'Catálogo KEV', icon: Target, module: 'kev', action: 'view' },
  { to: '/ejecuciones', label: 'Ejecuciones', icon: ArrowsClockwise, module: 'workflow', action: 'view' },
  { to: '/configuracion', label: 'Configuración', icon: SlidersHorizontal, module: 'settings', action: 'view' },
  { to: '/usuarios', label: 'Usuarios', icon: Users, module: 'users', action: 'view' },
  { to: '/roles', label: 'Roles y permisos', icon: ShieldCheck, module: 'roles', action: 'view' },
  { to: '/bitacora', label: 'Bitácora', icon: ClipboardText, module: 'audit', action: 'view' },
]

function useModuleTracking(enabled: boolean) {
  const { pathname } = useLocation()
  const tracker = useRef<ModuleTracker | null>(null)

  useEffect(() => {
    if (!enabled) return
    const t = new ModuleTracker((e) => sendKeepalive('/audit/navigation', e))
    tracker.current = t
    // Cierre u ocultamiento de pestaña: fetch con keepalive (sendBeacon no admite cabecera Authorization).
    const onVisibility = () => (document.visibilityState === 'hidden' ? t.suspend() : t.resume())
    const onHide = () => t.suspend()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', onHide)
      t.stop()
      tracker.current = null
    }
  }, [enabled])

  useEffect(() => {
    tracker.current?.go(moduleForPath(pathname))
  }, [pathname, enabled])
}

export function Shell() {
  const { user, logout, can, setUser } = useAuth()
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  useModuleTracking(Boolean(user))

  const toggleTheme = () => {
    const next = !dark
    applyTheme(next ? 'dark' : 'light')
    setDark(next)
    api.put<typeof user>('/auth/me/preferences', { theme: next ? 'dark' : 'light' })
      .then((u) => u && setUser(u))
      .catch(() => undefined)
  }

  const unread = useQuery({
    queryKey: ['alerts-unread'],
    queryFn: () => api.get<{ unread: number }>('/alerts/unread-count'),
    refetchInterval: 30_000,
    enabled: can('alerts', 'view'),
  }).data?.unread ?? 0
  const items = NAV.filter((n) => can(n.module, n.action))
  const link = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors duration-150 ${
      isActive ? 'bg-sunken font-medium text-ink' : 'text-muted hover:bg-sunken hover:text-ink'
    }`

  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <aside className="flex flex-col border-b border-line bg-surface md:min-h-screen md:border-r md:border-b-0">
        <div className="flex items-center gap-2 px-4 py-3.5">
          <span className="grid size-7 place-items-center rounded-md bg-accent text-accent-ink" aria-hidden>
            <Crosshair size={17} weight="bold" />
          </span>
          <div className="leading-tight">
            <div className="text-[14px] font-semibold">Radar KEV/EPSS</div>
            <div className="text-[11px] text-muted">Explotación activa</div>
          </div>
        </div>
        <nav aria-label="Principal" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-1 md:flex-col md:overflow-visible">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={link}>
              <Icon size={18} weight="regular" />
              {label}
              {to === '/alertas' && unread > 0 && (
                <span className="ml-auto rounded-full bg-danger px-1.5 text-[11px] font-semibold leading-[18px] text-bg" aria-label={`${unread} sin leer`}>{unread > 99 ? '99+' : unread}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-1 border-t border-line p-2">
          <NavLink to="/perfil" className={`${link} min-w-0 flex-1`}>
            <UserCircle size={18} weight="regular" />
            <span className="min-w-0">
              <span className="block truncate text-[13px] leading-tight">{user?.full_name}</span>
              <span className="block truncate text-[11px] font-normal text-muted">{user?.role}</span>
            </span>
          </NavLink>
          <button
            onClick={toggleTheme}
            aria-label={dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
            className="grid size-8 place-items-center rounded-md text-muted transition-[transform,background-color] duration-150 hover:bg-sunken hover:text-ink active:scale-[0.97]"
          >
            {dark ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button
            onClick={() => void logout()}
            aria-label="Cerrar sesión"
            className="grid size-8 place-items-center rounded-md text-muted transition-[transform,background-color] duration-150 hover:bg-sunken hover:text-ink active:scale-[0.97]"
          >
            <SignOut size={18} />
          </button>
        </div>
      </aside>
      <main className="min-w-0 px-4 py-5 md:px-7">
        <Outlet />
      </main>
    </div>
  )
}
