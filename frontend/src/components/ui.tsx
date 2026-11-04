import { CheckCircle, Minus, Warning, XCircle } from '@phosphor-icons/react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'

const press =
  'transition-[transform,background-color,border-color] duration-150 ease-[var(--ease-out-strong)] active:scale-[0.97] disabled:opacity-50 disabled:active:scale-100'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'
const variants: Record<Variant, string> = {
  primary: 'bg-accent text-accent-ink hover:brightness-110',
  secondary: 'border border-line-strong bg-surface text-ink hover:bg-sunken',
  danger: 'border border-line-strong bg-surface text-danger hover:bg-danger-soft',
  ghost: 'text-muted hover:bg-sunken hover:text-ink',
}

export function Button({
  variant = 'secondary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...props}
      className={`inline-flex h-8 pointer-coarse:h-11 items-center justify-center gap-1.5 rounded-md px-3 text-[13px] font-medium ${press} ${variants[variant]} ${className}`}
    />
  )
}

const control =
  'h-8 pointer-coarse:h-11 w-full rounded-md border border-line-strong bg-surface px-2.5 text-[13px] text-ink placeholder:text-muted'

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${control} ${props.className ?? ''}`} />
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${control} ${props.className ?? ''}`} />
}

export function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] font-medium text-muted">{label}</span>
      {children}
      {error && (
        <span role="alert" className="mt-1 block text-[12px] text-danger">
          {error}
        </span>
      )}
    </label>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-[20px] font-semibold leading-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Estado con color y además icono y texto (nunca solo color). */
export function StatusBadge({ kind, children }: { kind: 'ok' | 'warn' | 'danger' | 'neutral'; children: ReactNode }) {
  const styles = {
    ok: 'bg-ok-soft text-ok',
    warn: 'bg-warn-soft text-warn',
    danger: 'bg-danger-soft text-danger',
    neutral: 'bg-sunken text-muted',
  }[kind]
  const Icon = { ok: CheckCircle, warn: Warning, danger: XCircle, neutral: Minus }[kind]
  return (
    <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] font-medium ${styles}`}>
      <Icon size={13} weight="bold" aria-hidden />
      {children}
    </span>
  )
}

export function Skeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div role="status" aria-label="Cargando" className="divide-y divide-line">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex gap-4 px-3 py-3">
          {Array.from({ length: cols }, (_, c) => (
            <div key={c} className="h-3.5 flex-1 rounded bg-sunken motion-safe:animate-pulse" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="px-4 py-10 text-center">
      <p className="font-medium">{title}</p>
      {hint && <p className="mx-auto mt-1 max-w-md text-[13px] text-muted">{hint}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-4 py-10 text-center">
      <Warning size={22} className="text-danger" aria-hidden />
      <p className="font-medium">No se pudieron cargar los datos</p>
      <p className="text-[13px] text-muted">{message}</p>
      {onRetry && <Button onClick={onRetry}>Reintentar</Button>}
    </div>
  )
}

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border border-line bg-surface ${className}`}>{children}</div>
}

export const th = 'px-3 py-2 text-left text-[12px] font-medium text-muted border-b border-line whitespace-nowrap'
export const td = 'px-3 py-2 border-b border-line align-middle'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Diálogo modal accesible: foco dentro (trampa de Tab), Escape lo cierra y el foco vuelve a quien lo abrió.
 *  Ocurre pocas veces al día: puede animarse (≤200 ms); con movimiento reducido solo cambia la opacidad. */
export function Dialog({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}) {
  const reduce = useReducedMotion()
  const box = useRef<HTMLDivElement>(null)
  const close = useRef(onClose)
  useEffect(() => {
    close.current = onClose // el efecto de teclado siempre llama a la versión actual
  })

  useEffect(() => {
    if (!open) return
    const opener = document.activeElement as HTMLElement | null
    const first = box.current?.querySelector<HTMLElement>(FOCUSABLE)
    ;(first ?? box.current)?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') return close.current()
      if (e.key !== 'Tab' || !box.current) return
      const items = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
      if (items.length === 0) return e.preventDefault()
      const [head, tail] = [items[0], items[items.length - 1]]
      if (e.shiftKey && document.activeElement === head) { e.preventDefault(); tail.focus() }
      else if (!e.shiftKey && document.activeElement === tail) { e.preventDefault(); head.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      opener?.focus?.()
    }
  }, [open])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[12vh]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          <motion.div
            ref={box}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            tabIndex={-1}
            className="w-full max-w-md rounded-lg border border-line bg-surface p-5 outline-none"
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: 6 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.97 }}
            transition={{ duration: 0.18, ease: [0.23, 1, 0.32, 1] }}
          >
            <h2 className="mb-3 text-[16px] font-semibold">{title}</h2>
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** Props para una fila de tabla que se expande: alcanzable con Tab y accionable con Enter o Espacio. */
export function rowToggle(expanded: boolean, toggle: () => void) {
  return {
    tabIndex: 0,
    'aria-expanded': expanded,
    onClick: toggle,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        toggle()
      }
    },
    className: 'cursor-pointer hover:bg-sunken focus-visible:bg-sunken',
  }
}
