// Cuatro bahías distintas entre "Qué es el radar" y "Su inventario" (estructura de DESIGN.md): frase sola, grilla de puntos,
// dos tiles con gauge y una baldosa fotográfica con chips. Todas las entradas corren una sola vez (ver sección Motion).
import { animate, motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { Photo } from './Photo'

const EASE = [0.23, 1, 0.32, 1] as const
const gutter = 'px-4 md:px-8'
const bayPad = 'py-[clamp(56px,7vw,104px)]'
const title = 'max-w-[20ch] text-[clamp(30px,4.4vw,48px)] font-semibold leading-none tracking-[-0.003em]'
const body = 'max-w-[60ch] text-[17px] leading-[25px] tracking-[-0.022em]'

// Cita de la cifra de ~5 %: se completa a mano. Mientras esté vacía se muestra un marcador visible.
const FUENTE_CINCO_POR_CIENTO = ''

function Rise({ children, delay = 0, className = '' }: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '0px 0px -4% 0px' }}
      transition={{ duration: 0.5, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  )
}

/* ───────── Bahía 1: una sola frase ───────── */

export function BayRadar() {
  return (
    <section id="fundamentos" className={`dark relative scroll-mt-24 bg-surface text-ink ${gutter}`}>
      <div className="mx-auto flex min-h-[70vh] max-w-[1100px] items-center justify-center py-[clamp(56px,8vw,120px)]">
        <Rise>
          <h2 className="text-balance text-center text-[clamp(30px,5vw,56px)] font-semibold leading-[1.07] tracking-[-0.009em]">
            Una herramienta que responde, cada mañana, una sola pregunta: de todo lo que tengo expuesto, ¿qué ya está siendo atacado?
          </h2>
        </Rise>
      </div>
    </section>
  )
}

/* ───────── Bahía 2: la gravedad no basta (1000 puntos, ~5 % se enciende) ───────── */

const COLS = 50
const ROWS = 20
const TOTAL = COLS * ROWS
const LIT = 50 // ~5 % de 1000

// Selección reproducible (generador congruencial) para que los puntos encendidos no cambien entre cargas.
function pickLit(): number[] {
  let x = 20261103
  const set = new Set<number>()
  while (set.size < LIT) {
    x = (Math.imul(x, 1664525) + 1013904223) >>> 0
    set.add(x % TOTAL)
  }
  return [...set].sort((a, b) => a - b)
}

function DotGrid() {
  const ref = useRef<SVGSVGElement>(null)
  const inView = useInView(ref, { once: true, margin: '0px 0px -15% 0px' })
  const reduce = useReducedMotion()
  const lit = useMemo(() => pickLit(), [])
  const base = useMemo(() => Array.from({ length: TOTAL }, (_, i) => i), [])
  const pos = (i: number) => ({ cx: (i % COLS) * 10 + 5, cy: Math.floor(i / COLS) * 10 + 5 })
  return (
    <svg ref={ref} viewBox={`0 0 ${COLS * 10} ${ROWS * 10}`} className="block h-auto w-full" role="img" aria-label="Mil puntos que representan mil CVE publicados; unos cincuenta, resaltados en verde, son los que llegan a explotarse">
      {base.map((i) => (
        <circle key={i} {...pos(i)} r="1.9" fill="#86868b" />
      ))}
      {lit.map((i, k) => (
        <motion.circle
          key={i}
          {...pos(i)}
          r="2.6"
          fill="#00d959"
          initial={{ opacity: reduce ? 1 : 0 }}
          animate={{ opacity: inView || reduce ? 1 : 0 }}
          transition={{ duration: 0.5, ease: EASE, delay: reduce ? 0 : k * 0.03 }}
        />
      ))}
    </svg>
  )
}

export function BayGravedad() {
  return (
    <section className={`dark bg-bg text-ink ${gutter} ${bayPad}`}>
      <Rise>
        <h2 className={title}>La gravedad no basta</h2>
      </Rise>
      <Rise delay={0.05} className="mt-10">
        <DotGrid />
      </Rise>
      <div className="mt-10 grid gap-y-4 md:grid-cols-12 md:gap-x-6">
        <Rise className="md:col-span-5">
          <p className="text-[clamp(64px,9vw,96px)] font-semibold leading-none tracking-[-0.009em] text-battery-green tabular-nums">~5 %</p>
        </Rise>
        <Rise delay={0.06} className="md:col-span-7">
          <p className={body}>
            De cada 1000 CVE publicados, solo unos 50 llegan a explotarse. CVSS mide qué tan grave sería una falla en teoría, no si alguien ya la usa: parchar por CVSS deja al equipo corriendo detrás de listas que casi nadie ataca.
          </p>
          <p className="mt-3 text-[14px] leading-[1.29] text-muted">
            {FUENTE_CINCO_POR_CIENTO ? `Fuente: ${FUENTE_CINCO_POR_CIENTO}` : 'Fuente: [pendiente de cita]'}
          </p>
        </Rise>
      </div>
    </section>
  )
}

/* ───────── Bahía 3: KEV y EPSS, dos tiles del mismo alto ───────── */

function EpssGauge() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, margin: '0px 0px -10% 0px' })
  const reduce = useReducedMotion()
  const [n, setN] = useState(reduce ? 94 : 0)
  useEffect(() => {
    if (!inView || reduce) return
    const c = animate(0, 94, { duration: 0.7, ease: EASE, onUpdate: (v) => setN(Math.round(v)) })
    return () => c.stop()
  }, [inView, reduce])
  return (
    <div ref={ref} className="relative w-full max-w-[360px]">
      <svg viewBox="0 0 200 108" className="w-full" aria-hidden>
        <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="rgba(245,245,247,0.18)" strokeWidth="10" strokeLinecap="round" />
        <motion.path
          d="M 10 100 A 90 90 0 0 1 190 100"
          fill="none"
          stroke="#f5f5f7"
          strokeWidth="10"
          strokeLinecap="round"
          initial={{ pathLength: reduce ? 0.94 : 0 }}
          animate={{ pathLength: inView || reduce ? 0.94 : 0 }}
          transition={{ duration: 0.7, ease: EASE }}
        />
      </svg>
      <p className="absolute inset-x-0 bottom-0 text-center text-[clamp(40px,5vw,56px)] font-semibold leading-[0.9] tabular-nums tracking-[-0.009em]" aria-hidden>
        {n} %
      </p>
      <span className="sr-only">94 % de probabilidad de explotación en 30 días</span>
    </div>
  )
}

const tile = 'flex h-full flex-col rounded-[28px] bg-sunken p-6 md:p-8'

export function BayKevEpss() {
  return (
    <section className={`dark bg-surface text-ink ${gutter} ${bayPad}`}>
      <Rise>
        <h2 className={title}>KEV y EPSS: lo que se explota y lo que se explotará</h2>
        <p className={`${body} mt-5`}>
          El catálogo KEV de CISA reúne los CVE con explotación activa confirmada, con fecha de alta y plazo de remediación. EPSS, de FIRST, estima de 0 a 100 % la probabilidad de explotación en 30 días y sirve para ordenar lo que aún no está en KEV.
        </p>
      </Rise>
      <div className="mt-10 grid gap-6 md:grid-cols-2 md:items-stretch">
        <Rise>
          <article className={tile}>
            <span className="inline-block self-start rounded-[5px] bg-danger px-2 py-0.5 text-[14px] font-semibold text-surface">En KEV</span>
            <p className="mt-6 text-[clamp(36px,4.4vw,48px)] font-semibold leading-none tracking-[-0.009em]">Ya la explotan</p>
            <p className="mt-3 text-[17px] leading-[25px] tracking-[-0.022em]">Un ataque confirmado pesa más que cualquier probabilidad: el puntaje nunca baja de 70.</p>
            <dl className="mt-auto pt-8">
              <dt className="text-[14px] text-muted">Fecha límite de CISA</dt>
              <dd className="mt-1 text-[clamp(28px,3vw,32px)] font-semibold leading-[1.13] tracking-[0.004em]">En 3 días</dd>
              <dd className="mt-1 text-[14px] text-muted">Ejemplo: CVE-2024-3400. Datos de demostración.</dd>
            </dl>
          </article>
        </Rise>
        <Rise delay={0.08}>
          <article className={tile}>
            <span className="inline-block self-start rounded-[5px] bg-control px-2 py-0.5 text-[14px] font-semibold">EPSS</span>
            <p className="mt-6 text-[clamp(36px,4.4vw,48px)] font-semibold leading-none tracking-[-0.009em]">La explotarán</p>
            <p className="mt-3 text-[17px] leading-[25px] tracking-[-0.022em]">Probabilidad de que se explote en los próximos 30 días, de 0 a 100 %.</p>
            <div className="mt-auto flex flex-col gap-2 pt-8">
              <EpssGauge />
              <p className="text-[14px] text-muted">Ejemplo con datos de demostración.</p>
            </div>
          </article>
        </Rise>
      </div>
    </section>
  )
}

/* ───────── Bahía 4: su inventario, baldosa con foto y chips con barra de peso ───────── */

const ACTIVOS = [
  { host: 'fw-borde-01', crit: 'Crítica', env: 'Producción', weight: 1 },
  { host: 'app-pagos', crit: 'Alta', env: 'Producción', weight: 0.75 },
  { host: 'dev-sandbox', crit: 'Baja', env: 'Desarrollo', weight: 0.25 },
]

function AssetChip({ a, on, delay }: { a: (typeof ACTIVOS)[number]; on: boolean; delay: number }) {
  return (
    <li className="rounded-[28px] bg-chip p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[17px] font-semibold tracking-[-0.022em]">{a.host}</span>
        <span className="text-[14px] tabular-nums text-ink/80">Peso {a.weight.toFixed(2).replace('.', ',')}</span>
      </div>
      <p className="mt-0.5 text-[14px] text-ink/80">
        {a.crit} · {a.env}
      </p>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-ink/20" aria-hidden>
        <motion.div className="h-full origin-left rounded-full bg-ink" initial={false} animate={{ scaleX: on ? a.weight : 0 }} transition={{ duration: 0.6, ease: EASE, delay }} />
      </div>
    </li>
  )
}

export function BayInventario() {
  const ref = useRef<HTMLUListElement>(null)
  const inView = useInView(ref, { once: true, margin: '0px 0px -15% 0px' })
  const reduce = useReducedMotion()
  const on = inView || !!reduce
  return (
    <section className={`dark bg-bg text-ink ${gutter} ${bayPad}`}>
      <Rise>
        <h2 className={title}>Su inventario: lo que le afecta</h2>
        <p className={`${body} mt-5`}>
          Un CVE solo importa si está en un activo suyo. El radar cruza cada hallazgo con su inventario y pondera la criticidad del activo y su entorno, para que un servidor de producción pese más que uno de pruebas.
        </p>
      </Rise>
      <Rise delay={0.05} className="mt-10">
        <div className="relative overflow-hidden rounded-[28px] bg-surface p-6 md:p-12">
          <Photo name="servers-1-tyler" alt="Pasillo de un centro de datos con racks de servidores iluminados" sizes="(min-width: 1100px) 1300px, 100vw" className="absolute inset-0 size-full" />
          <div className="absolute inset-0 bg-black/70" aria-hidden />
          <ul ref={ref} className="relative mx-auto grid max-w-[900px] gap-3 pt-[clamp(80px,16vw,220px)] md:grid-cols-3">
            {ACTIVOS.map((a, i) => (
              <AssetChip key={a.host} a={a} on={on} delay={reduce ? 0 : 0.15 + i * 0.12} />
            ))}
          </ul>
          <p className="relative mx-auto mt-4 max-w-[900px] text-[14px] text-ink/80">Datos de demostración.</p>
        </div>
      </Rise>
    </section>
  )
}
