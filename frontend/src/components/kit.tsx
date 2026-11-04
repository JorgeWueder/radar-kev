// Componentes compartidos del panel (Fase 1): Meta (texto/ícono en gris), KpiCard, DataTable con header fijo,
// Pagination y DetailDrawer. Regla de color: en tablas, una sola pill de color por fila (la del riesgo).
import { X } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Fragment, useRef, type ComponentType, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Button, EmptyState, ErrorState, Panel, Skeleton, td, th, useModalFocus } from './ui'

/** Dato secundario de una fila: texto (y opcionalmente ícono) en gris. Solo `alert` lo pone en rojo (p. ej. SLA vencido). */
export function Meta({
  icon: Icon,
  alert = false,
  children,
}: {
  icon?: ComponentType<{ size?: number; weight?: 'regular' | 'bold'; 'aria-hidden'?: boolean }>
  alert?: boolean
  children: ReactNode
}) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap ${alert ? 'font-medium text-danger' : 'text-muted'}`}>
      {Icon && <Icon size={13} weight={alert ? 'bold' : 'regular'} aria-hidden />}
      {children}
    </span>
  )
}

/** Tarjeta de indicador. `hero` es la cifra principal de la pantalla; la normal va en fila. Con `to` enlaza a su lista filtrada. */
export function KpiCard({
  label,
  value,
  sub,
  to,
  hero = false,
  tone,
  icon: Icon,
  children,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  to?: string
  hero?: boolean
  tone?: 'danger' | 'warn'
  icon?: ComponentType<{ size?: number; weight?: 'regular'; 'aria-hidden'?: boolean }>
  children?: ReactNode
}) {
  const base = hero ? 'rounded-[28px] bg-sunken p-6 md:p-8' : 'rounded-lg border border-line bg-surface p-4'
  const body = (
    <>
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-muted">
        {Icon && <Icon size={14} weight="regular" aria-hidden />}
        {label}
      </div>
      <div className={`mt-1 font-semibold leading-none tabular-nums tracking-[-0.009em] ${hero ? 'text-[clamp(48px,6vw,64px)]' : 'text-[28px]'} ${tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warn' : ''}`}>{value}</div>
      {sub && <div className={`mt-2 text-muted ${hero ? 'text-[14px]' : 'text-[12px]'}`}>{sub}</div>}
      {children}
    </>
  )
  if (to) {
    return (
      <Link to={to} className={`block ${base} transition-[background-color,border-color] duration-150 hover:border-line-strong ${hero ? 'hover:bg-control' : ''}`}>
        {body}
      </Link>
    )
  }
  return <div className={base}>{body}</div>
}

/** Props de una fila que abre su detalle: clic o Enter/Espacio, alcanzable con Tab. */
export function rowOpen(open: () => void, className = '') {
  return {
    tabIndex: 0,
    onClick: open,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.target !== e.currentTarget) return // no intercepta teclas de controles dentro de la fila
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        open()
      }
    },
    className: `cursor-pointer hover:bg-sunken focus-visible:bg-sunken ${className}`,
  }
}

/** Evita que un control dentro de una fila abra el detalle de la fila. */
export function stop(e: { stopPropagation: () => void }) {
  e.stopPropagation()
}

/** Pestañas accesibles (tablist): flechas izquierda/derecha cambian de pestaña. El contenido va en un `role="tabpanel"` del llamador. */
export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: Array<{ id: T; label: string }>; value: T; onChange: (id: T) => void; label: string }) {
  const onKey = (e: React.KeyboardEvent) => {
    const i = tabs.findIndex((t) => t.id === value)
    if (e.key === 'ArrowRight') onChange(tabs[(i + 1) % tabs.length].id)
    else if (e.key === 'ArrowLeft') onChange(tabs[(i - 1 + tabs.length) % tabs.length].id)
  }
  return (
    <div role="tablist" aria-label={label} onKeyDown={onKey} className="mb-4 flex flex-wrap gap-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          id={`tab-${t.id}`}
          type="button"
          role="tab"
          aria-selected={value === t.id}
          aria-controls={`panel-${t.id}`}
          tabIndex={value === t.id ? 0 : -1}
          onClick={() => onChange(t.id)}
          className={`h-8 rounded-full px-4 text-[13px] transition-colors duration-150 pointer-coarse:h-11 ${value === t.id ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export interface Column<T> {
  key: string
  header: ReactNode
  cell: (row: T) => ReactNode
  /** Clases extra de la celda (p. ej. `text-right tabular-nums`). */
  className?: string
  headerClassName?: string
  ariaSort?: 'ascending' | 'descending' | 'none'
}

/** Tabla de datos: header fijo, carga con skeleton, error con reintento y vacío. Sin animaciones salvo el skeleton. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  onRetry,
  empty,
  rowProps,
  rowClassName,
  expanded,
  skeletonRows = 8,
  maxHeight = 'max-h-[calc(100svh-17rem)]',
}: {
  columns: Column<T>[]
  rows: T[] | undefined
  rowKey: (row: T) => string
  loading?: boolean
  error?: string
  onRetry?: () => void
  empty: ReactNode
  rowProps?: (row: T) => React.HTMLAttributes<HTMLTableRowElement>
  rowClassName?: (row: T) => string
  /** Contenido de una fila expandida (se pinta bajo la fila, ocupando todas las columnas). */
  expanded?: (row: T) => ReactNode
  skeletonRows?: number
  maxHeight?: string
}) {
  return (
    <Panel className={`overflow-auto ${maxHeight}`}>
      {loading ? (
        <Skeleton cols={columns.length} rows={skeletonRows} />
      ) : error ? (
        <ErrorState message={error} onRetry={onRetry} />
      ) : !rows || rows.length === 0 ? (
        empty
      ) : (
        <table className="w-full border-separate border-spacing-0 text-[13px]">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={`${th} ${c.headerClassName ?? (c.className?.includes('text-right') ? 'text-right' : '')}`} aria-sort={c.ariaSort}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const extra = rowProps?.(r) ?? {}
              const { className: rp, ...rest } = extra
              const more = expanded?.(r)
              return (
                <Fragment key={rowKey(r)}>
                  <tr {...rest} className={`${rp ?? ''} ${rowClassName?.(r) ?? ''}`}>
                    {columns.map((c) => (
                      <td key={c.key} className={`${td} ${c.className ?? ''}`}>
                        {c.cell(r)}
                      </td>
                    ))}
                  </tr>
                  {more && (
                    <tr>
                      <td colSpan={columns.length} className="border-b border-line bg-sunken px-4 py-3">
                        {more}
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

export function Pagination({ page, total, pageSize, onPage }: { page: number; total: number; pageSize: number; onPage: (p: number) => void }) {
  if (total <= pageSize) return null
  return (
    <div className="mt-3 flex items-center justify-between text-[13px] text-muted">
      <span>
        {page * pageSize + 1}–{Math.min((page + 1) * pageSize, total)} de {total}
      </span>
      <div className="flex gap-2">
        <Button disabled={page === 0} onClick={() => onPage(page - 1)}>
          Anterior
        </Button>
        <Button disabled={(page + 1) * pageSize >= total} onClick={() => onPage(page + 1)}>
          Siguiente
        </Button>
      </div>
    </div>
  )
}

/** Panel lateral derecho para el detalle de una fila. Se anima solo al abrir/cerrar (≤ 0,45 s, ease-out); con movimiento reducido solo cambia la opacidad. */
export function DetailDrawer({ open, onClose, title, subtitle, children }: { open: boolean; onClose: () => void; title: string; subtitle?: string; children: ReactNode }) {
  const reduce = useReducedMotion()
  const box = useRef<HTMLDivElement>(null)
  useModalFocus(open, onClose, box)
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex justify-end bg-black/40"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.aside
            ref={box}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            className="flex h-full w-full max-w-[480px] flex-col border-l border-line bg-surface outline-none"
            initial={reduce ? { opacity: 0 } : { opacity: 0, x: 32 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, x: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, x: 32 }}
            transition={{ duration: 0.4, ease: [0.23, 1, 0.32, 1] }}
          >
            <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
              <div className="min-w-0">
                <h2 className="break-words text-[18px] font-semibold leading-tight">{title}</h2>
                {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Cerrar detalle"
                className="grid size-8 shrink-0 place-items-center rounded-full text-muted transition-[transform,background-color] duration-150 hover:bg-sunken hover:text-ink active:scale-[0.97] pointer-coarse:size-11"
              >
                <X size={18} />
              </button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** Fila etiqueta/valor para el cuerpo de un drawer. */
export function DrawerRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-b border-line py-2.5 last:border-b-0">
      <dt className="text-[12px] font-medium text-muted">{label}</dt>
      <dd className="mt-0.5 text-[13px]">{children}</dd>
    </div>
  )
}

export { EmptyState }
