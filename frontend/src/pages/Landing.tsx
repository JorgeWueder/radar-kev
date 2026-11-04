import { ArrowRight, CaretDown, Crosshair } from '@phosphor-icons/react'
import { motion, useMotionValueEvent, useReducedMotion, useScroll } from 'motion/react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import {
  BandTag,
  ComparisonFragment,
  CvssFragment,
  EpssFragment,
  InventoryFragment,
  KevFragment,
  RankingFragment,
  RunFragment,
  TicketFragment,
} from '../landing/Fragments'
import { useAuth } from '../lib/auth'
import { bandOf, BAND_LABEL, PARAMS, riskScore, type ScoreInput } from '../lib/score'

const EASE = [0.23, 1, 0.32, 1] as const

// Correo para pedir una demostración: se define al compilar (VITE_CONTACT_EMAIL). Sin él, el botón no se muestra.
const CONTACT = (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_CONTACT_EMAIL

const btn =
  'inline-flex items-center justify-center gap-2 rounded-full bg-accent px-5 py-2.5 text-[15px] font-medium text-accent-ink transition-[transform,opacity] duration-150 ease-out hover:opacity-90 active:scale-[0.97]'
const FLOAT = 'shadow-lg' // taste-skill-ignore: el menú flotante sí lleva sombra
const gutter = 'px-4 md:px-8'
const section = 'py-[clamp(88px,12vw,180px)]'
const h2 = 'text-[clamp(40px,5vw,80px)] font-semibold leading-[1] tracking-[-0.01em]'
const fmt = (n: number, d = 2) => n.toFixed(d).replace('.', ',')

function Reveal({ children, delay = 0, className = '', kind = 'rise' }: { children: ReactNode; delay?: number; className?: string; kind?: 'rise' | 'wipe' }) {
  const reduce = useReducedMotion()
  const hidden = kind === 'wipe' && !reduce ? { opacity: 1, clipPath: 'inset(0 100% 0 0)' } : { opacity: 0, y: reduce || kind === 'wipe' ? 0 : 24 }
  const shown = kind === 'wipe' && !reduce ? { opacity: 1, clipPath: 'inset(0 0% 0 0)' } : { opacity: 1, y: 0 }
  return (
    <motion.div
      className={className}
      initial={hidden}
      whileInView={shown}
      viewport={{ once: true, margin: '0px 0px -10% 0px' }}
      transition={{ duration: kind === 'wipe' ? 0.6 : 0.4, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  )
}

/* ───────────────────────── Cabecera ───────────────────────── */

const NAV = [
  ['Fundamentos', '#fundamentos'],
  ['Cómo funciona', '#funcionamiento'],
  ['Calculadora', '#calculadora'],
  ['Preguntas', '#preguntas'],
] as const

function useActiveSection() {
  const [active, setActive] = useState('')
  useEffect(() => {
    const els = NAV.map(([, h]) => document.getElementById(h.slice(1))).filter((e): e is HTMLElement => !!e)
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setActive(e.target.id)),
      { rootMargin: '-40% 0px -55% 0px' },
    )
    els.forEach((e) => io.observe(e))
    return () => io.disconnect()
  }, [])
  return active
}

function MobileMenu({ active }: { active: string }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
  return (
    <div className="relative lg:hidden">
      <button type="button" aria-expanded={open} aria-controls="menu-movil" onClick={() => setOpen((o) => !o)} className="min-h-[44px] px-2 transition-opacity duration-150 active:scale-[0.97]">
        Menú
      </button>
      {open && (
        <ul id="menu-movil" className={`menu-pop absolute right-0 top-full z-40 mt-1 w-52 rounded-[20px] bg-surface p-1.5 ${FLOAT}`}>
          {NAV.map(([label, href]) => (
            <li key={href}>
              <a
                href={href}
                onClick={() => setOpen(false)}
                aria-current={active === href.slice(1) ? 'location' : undefined}
                className={`block rounded-full px-4 py-3 transition-colors duration-150 hover:bg-sunken ${active === href.slice(1) ? 'bg-sunken font-medium' : ''}`}
              >
                {label}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Header() {
  const { user } = useAuth()
  const active = useActiveSection()
  return (
    <header className={`sticky top-0 z-30 flex h-14 items-center justify-between bg-bg ${gutter}`}>
      <a href="#inicio" className="flex items-center gap-2 text-[15px] font-semibold">
        <span className="grid size-7 place-items-center rounded-[10px] bg-accent text-accent-ink" aria-hidden>
          <Crosshair size={18} weight="bold" />
        </span>
        Radar KEV/EPSS
      </a>
      <nav aria-label="Principal" className="flex items-center gap-3 text-[15px] lg:gap-5">
        <MobileMenu active={active} />
        {NAV.map(([label, href]) => (
          <a
            key={href}
            href={href}
            aria-current={active === href.slice(1) ? 'location' : undefined}
            className={`hidden transition-colors hover:text-link lg:inline ${active === href.slice(1) ? 'font-medium text-link' : ''}`}
          >
            {label}
          </a>
        ))}
        <Link to={user ? '/resumen' : '/login'} className={`${btn} !py-1.5`}>
          {user ? 'Ir al panel' : 'Ingresar'}
        </Link>
      </nav>
    </header>
  )
}

/* ───────────────────────── Portada ───────────────────────── */

const TABS = ['Lista priorizada', 'Ejecución diaria', 'Ticket con plazo']
const CAPTIONS = ['Lo ya explotado queda arriba de la lista.', 'Cada día se cruza el catálogo con su inventario.', 'Cada coincidencia nueva abre un ticket con plazo.']

function Hero() {
  const { user } = useAuth()
  const reduce = useReducedMotion()
  const ref = useRef<HTMLElement>(null)
  const [step, setStep] = useState(0)
  const [pinned, setPinned] = useState(false)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  const pin = pinned && !reduce

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const sync = () => setPinned(mq.matches)
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  useMotionValueEvent(scrollYProgress, 'change', (p) => {
    if (pin) setStep(Math.min(TABS.length - 1, Math.floor(p * TABS.length)))
  })

  const go = (i: number) => {
    if (pin && ref.current) {
      const range = ref.current.offsetHeight - window.innerHeight
      window.scrollTo({ top: ref.current.offsetTop + ((i + 0.02) / TABS.length) * range, behavior: reduce ? 'auto' : 'smooth' })
    }
    setStep(i)
  }

  const frames = [<RankingFragment key="r" compact={!pinned} />, <RunFragment key="e" />, <TicketFragment key="t" />]

  return (
    <section id="inicio" ref={ref} className={reduce ? '' : 'lg:h-[220svh]'}>
      <div className={`${gutter} flex flex-col gap-8 pb-12 pt-4 lg:grid lg:grid-cols-[5fr_6fr] lg:items-center lg:gap-14 lg:pb-8 ${pin ? 'lg:sticky lg:top-14 lg:h-[calc(100svh-3.5rem)]' : 'lg:min-h-[calc(100svh-3.5rem)]'}`}>
        <div>
          <h1 className="text-[clamp(40px,5.4vw,92px)] font-semibold leading-[1] tracking-[-0.01em]">Parche primero lo que ya explotan</h1>
          <p className="mt-8 max-w-[34ch] text-[18px] leading-snug">
            Cruza cada día su inventario con el catálogo KEV de CISA (las vulnerabilidades que ya se atacan) y con EPSS de FIRST (la probabilidad de que se ataquen), y le dice qué arreglar primero.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-6 gap-y-3">
            <Link to={user ? '/resumen' : '/login'} className={btn}>
              {user ? 'Ir al panel' : 'Ingresar al radar'} <ArrowRight weight="bold" />
            </Link>
            {CONTACT && (
              <a href={`mailto:${CONTACT}?subject=Demostración del Radar KEV/EPSS`} className="text-[15px] underline underline-offset-4 transition-colors hover:text-link">
                Pedir una demostración
              </a>
            )}
          </div>
        </div>
        <div>
          <div className="relative aspect-[4/3] w-full overflow-hidden rounded-[28px] bg-surface sm:aspect-[16/10] lg:aspect-[16/11]" role="img" aria-label="Ejemplo de la interfaz del radar con datos de demostración">
            {frames.map((f, i) => (
              <motion.div
                key={i}
                className="absolute inset-0 grid place-items-center p-3 lg:p-6"
                aria-hidden
                initial={false}
                animate={{ opacity: i === step ? 1 : 0, y: reduce ? 0 : i === step ? 0 : i < step ? -40 : 40 }}
                transition={{ duration: 0.35, ease: EASE }}
              >
                <div className="w-full">{f}</div>
              </motion.div>
            ))}
          </div>
          <div role="tablist" aria-label="Ejemplos de la interfaz" className="mt-3 flex flex-wrap gap-1.5">
            {TABS.map((t, i) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={i === step}
                onClick={() => go(i)}
                className={`min-h-[44px] rounded-full px-4 text-[15px] transition-[background-color,transform] duration-150 ease-out active:scale-[0.97] ${i === step ? 'bg-control font-medium' : 'hover:bg-sunken'}`}
              >
                {t}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[15px] text-muted">
            {CAPTIONS[step]} Datos de demostración.
          </p>
        </div>
      </div>
    </section>
  )
}

/* ───────────────────────── Fotografía (una, con el tono de la app) ───────────────────────── */

function Radar({ className = '' }: { className?: string }) {
  return (
    <Reveal className={className}>
      <figure>
        <Reveal kind="wipe" className="aspect-[4/3] w-full overflow-hidden rounded-[28px] bg-accent md:aspect-[21/9]">
          <img
            src="/fotos/radar-rt70.jpg"
            width={1920}
            height={1280}
            alt="Gran antena parabólica del radar planetario RT-70 bajo un cielo despejado, en tono azul"
            loading="lazy"
            decoding="async"
            className="size-full object-cover mix-blend-multiply grayscale"
          />
        </Reveal>
        <figcaption className="mt-3 max-w-[60ch] text-[15px] opacity-80">Radar planetario RT-70, Crimea: una antena que mira lejos para ver lo que se acerca.</figcaption>
      </figure>
    </Reveal>
  )
}

/* ───────────────────────── Fundamentos ───────────────────────── */

const FUNDAMENTOS: Array<{ title: string; body: string; pic: ReactNode }> = [
  {
    title: 'La gravedad no basta',
    body: 'Cada año se publican decenas de miles de CVE. CVSS mide qué tan grave sería una falla en teoría, no si alguien ya la usa. Parchar por CVSS deja al equipo corriendo detrás de listas que casi nadie ataca.',
    pic: <CvssFragment />,
  },
  {
    title: 'KEV y EPSS: lo que se explota y lo que se explotará',
    body: 'El catálogo KEV de CISA reúne los CVE con explotación activa confirmada, con fecha de alta y plazo de remediación. EPSS, de FIRST, estima de 0 a 100 % la probabilidad de explotación en 30 días y sirve para ordenar lo que aún no está en KEV.',
    pic: (
      <div className="space-y-3">
        <KevFragment />
        <EpssFragment />
      </div>
    ),
  },
  {
    title: 'Su inventario: lo que le afecta',
    body: 'Un CVE solo importa si está en un activo suyo. El radar cruza cada hallazgo con su inventario y pondera la criticidad del activo y su entorno, para que un servidor de producción pese más que uno de pruebas.',
    pic: <InventoryFragment />,
  },
]

function Fundamentos() {
  return (
    <section id="fundamentos" className={`scroll-mt-14 ${gutter} ${section}`}>
      <div className="grid gap-y-10 lg:grid-cols-12 lg:gap-x-6">
        <Reveal className="lg:col-span-8 lg:col-start-5">
          <h2 className={h2}>Qué es el radar</h2>
          <p className="mt-5 max-w-2xl text-[20px] leading-snug">Una herramienta que responde, cada mañana, una sola pregunta: de todo lo que tengo expuesto, ¿qué ya está siendo atacado?</p>
        </Reveal>
        {FUNDAMENTOS.map((f) => (
          <div key={f.title} className="lg:col-span-12 lg:grid lg:grid-cols-12 lg:gap-x-6 lg:py-[clamp(12px,2vw,28px)]">
            <Reveal className="lg:col-span-5 lg:col-start-5">
              <h3 className="max-w-[22ch] text-[clamp(26px,2.8vw,44px)] font-semibold leading-[1.05] tracking-[-0.01em]">{f.title}</h3>
              <p className="mt-3 max-w-[42ch] text-[17px] leading-relaxed">{f.body}</p>
            </Reveal>
            <Reveal delay={0.08} className="mt-5 lg:col-span-3 lg:col-start-10 lg:mt-0">
              {f.pic}
            </Reveal>
          </div>
        ))}
      </div>
    </section>
  )
}

function Contraste() {
  return (
    <section className={`${gutter} pb-[clamp(64px,10vw,140px)]`}>
      <Reveal>
        <h2 className="max-w-[18ch] text-[clamp(30px,3.6vw,52px)] font-semibold leading-[1.05] tracking-[-0.01em]">Dos CVE, dos prioridades</h2>
        <p className="mb-8 mt-4 max-w-[60ch] text-[17px] leading-relaxed">
          Con el mismo activo, el CVE de la izquierda es más grave en el papel; el de la derecha ya está en el catálogo KEV. El radar pone primero el segundo.
        </p>
      </Reveal>
      <Reveal delay={0.08}>
        <ComparisonFragment />
      </Reveal>
    </section>
  )
}

/* ───────────────────────── Cómo funciona ───────────────────────── */

const STAGES = [
  { time: 'Unos minutos', text: 'Primero, descarga el catálogo KEV y los valores EPSS del día desde sus fuentes públicas.', cls: 'bg-accent text-accent-ink' },
  { time: 'Segundos', text: 'Después, cruza cada CVE con su inventario y calcula el puntaje con la fórmula vigente.', cls: 'bg-ink text-bg' },
  { time: 'Al instante', text: 'Luego, abre una alerta y un ticket por cada coincidencia nueva y envía un solo resumen.', cls: 'bg-accent text-accent-ink' },
  { time: 'Hasta su plazo', text: 'Por último, el equipo remedia dentro del plazo: de 15 a 180 días según la banda, o la fecha límite de CISA si está en KEV.', cls: 'bg-ink text-bg' },
]

function Funcionamiento() {
  return (
    <section id="funcionamiento" className={`scroll-mt-14 ${gutter} ${section}`}>
      <Reveal>
        <h2 className="max-w-[14ch] text-[clamp(44px,6vw,96px)] font-semibold leading-[0.98] tracking-[-0.01em]">Cada día, sin que nadie lo pida</h2>
      </Reveal>
      <div className="mt-16 grid gap-[6px] md:grid-cols-4" data-ui>
        {STAGES.map((s, i) => (
          <Reveal key={s.time} kind="wipe" delay={i * 0.12} className={`min-h-[72px] rounded-[28px] p-5 md:h-[22vh] ${s.cls}`}>
            <span className="text-[clamp(20px,2vw,30px)] font-semibold leading-tight">{s.time}</span>
          </Reveal>
        ))}
      </div>
      <ol className="mt-5 grid gap-5 md:grid-cols-4 md:gap-[6px]">
        {STAGES.map((s) => (
          <li key={s.time} className="max-w-[28ch] text-[17px] leading-snug md:pr-4">
            {s.text}
          </li>
        ))}
      </ol>
    </section>
  )
}

/* ───────────────────────── Calculadora ───────────────────────── */

const CRIT = ['Baja', 'Media', 'Alta', 'Crítica']

const PRESETS: Array<{ label: string; v: ScoreInput }> = [
  { label: 'Crítico en KEV', v: { inKev: true, ransomware: true, epss: 0.94, percentile: 0.99, cvss: 9.8, criticality: 4 } },
  { label: 'Alto fuera de KEV', v: { inKev: false, ransomware: false, epss: 0.35, percentile: 0.9, cvss: 8.8, criticality: 3 } },
  { label: 'Bajo en pruebas', v: { inKev: false, ransomware: false, epss: 0.05, percentile: 0.6, cvss: 6.5, criticality: 1 } },
]

function Slider({ label, value, min, max, step, onChange, format }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; format: (v: number) => string }) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between text-[15px]">
        {label}
        <span className="font-medium tabular-nums">{format(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-1 h-7 w-full cursor-pointer accent-accent" />
    </label>
  )
}

function Check({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className={`flex min-h-[44px] items-center gap-2.5 text-[15px] ${disabled ? 'opacity-50' : 'cursor-pointer'}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="size-5 accent-accent" />
      {label}
    </label>
  )
}

function Calculadora() {
  const [v, setV] = useState<ScoreInput>(PRESETS[0].v)
  const set = (patch: Partial<ScoreInput>) => setV((s) => ({ ...s, ...patch }))

  const score = useMemo(() => riskScore(v), [v])
  const band = bandOf(score)
  const base = PARAMS.wEpss * v.epss + PARAMS.wPercentile * v.percentile + PARAMS.wCvss * (v.cvss / 10) + PARAMS.wAsset * (v.criticality / 4)
  const sla = v.inKev ? 'el plazo que fija CISA para ese CVE' : `${PARAMS.sla[band]} días desde la detección`
  const resultado = v.inKev
    ? `Con KEV: ${PARAMS.kevFloor} + ${100 - PARAMS.kevFloor} × ${fmt(base)}${v.ransomware ? ` + ${PARAMS.ransomwareBonus}` : ''} = ${fmt(score)}${score >= 100 ? ' (tope 100)' : ''}`
    : `Sin KEV: ${PARAMS.kevFloor - 1} × ${fmt(base)} = ${fmt(score)}`

  return (
    <section id="calculadora" className="scroll-mt-14 bg-sunken">
      <div className={`${gutter} flex flex-col gap-8 py-[clamp(56px,8vw,120px)] lg:grid lg:grid-cols-2 lg:gap-x-16`}>
        <div className="sticky top-14 z-10 -mx-4 bg-sunken px-4 py-3 lg:static lg:col-start-2 lg:row-start-1 lg:mx-0 lg:p-0">
          <div className="lg:sticky lg:top-24">
            <p className="flex items-baseline gap-2 font-semibold leading-[0.85] tabular-nums tracking-[-0.01em]" aria-live="polite" aria-atomic>
              <span className="text-[clamp(64px,9vw,150px)]">{Math.round(score)}</span>
              <span className="text-[clamp(20px,2.4vw,36px)] text-muted">/100</span>
              <span className="ml-3 self-center text-[18px] tracking-normal">
                <BandTag band={band} />
                <span className="sr-only">{BAND_LABEL[band]}</span>
              </span>
            </p>
            <p className="mt-4 hidden max-w-[40ch] text-[17px] leading-snug lg:block">
              Plazo de remediación: {sla}. Un CVE en KEV nunca baja de {PARAMS.kevFloor}; uno fuera de KEV nunca lo alcanza.
            </p>
            <div className="mt-6 hidden max-w-[52ch] space-y-2 text-[15px] leading-snug text-muted lg:block">
              <p>
                Base = {fmt(PARAMS.wEpss)} × EPSS + {fmt(PARAMS.wPercentile)} × percentil + {fmt(PARAMS.wCvss)} × CVSS/10 + {fmt(PARAMS.wAsset)} × criticidad/4 = <span className="font-medium text-ink">{fmt(base)}</span>
              </p>
              <p className="font-medium text-ink">{resultado}</p>
            </div>
          </div>
        </div>
        <div className="lg:col-start-1 lg:row-start-1">
          <Reveal>
            <h2 className="text-[clamp(30px,3.4vw,44px)] font-semibold leading-[1.05] tracking-[-0.01em]">¿Qué puntaje tendría su CVE?</h2>
            <div className="mt-5 flex flex-wrap gap-1.5" role="group" aria-label="Ejemplos">
              {PRESETS.map((p) => (
                <button key={p.label} type="button" onClick={() => setV(p.v)} className="min-h-[44px] rounded-full bg-control px-4 text-[15px] transition-transform duration-150 ease-out hover:brightness-110 active:scale-[0.97]">
                  {p.label}
                </button>
              ))}
            </div>
          </Reveal>
          <div data-ui className="mt-5 grid max-w-3xl gap-x-10 gap-y-3 rounded-[28px] bg-surface p-6 md:grid-cols-2">
            <div className="space-y-1">
              <Check label="Está en el catálogo KEV" checked={v.inKev} onChange={(c) => set({ inKev: c, ransomware: c ? v.ransomware : false })} />
              <Check label="Usado por ransomware (solo en KEV)" checked={v.ransomware && v.inKev} onChange={(c) => set({ ransomware: c })} disabled={!v.inKev} />
              <label className="block pt-1">
                <span className="text-[15px]">Criticidad del activo</span>
                <select value={v.criticality} onChange={(e) => set({ criticality: Number(e.target.value) })} className="mt-1 block min-h-[44px] w-full rounded-full border border-line-strong bg-surface px-2 text-[15px] md:min-h-[36px]">
                  {CRIT.map((c, i) => (
                    <option key={c} value={i + 1}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="space-y-2">
              <Slider label="EPSS" value={v.epss} min={0} max={1} step={0.01} onChange={(x) => set({ epss: x })} format={(x) => `${Math.round(x * 100)} %`} />
              <Slider label="Percentil EPSS" value={v.percentile} min={0} max={1} step={0.01} onChange={(x) => set({ percentile: x })} format={(x) => `${Math.round(x * 100)} %`} />
              <Slider label="CVSS" value={v.cvss} min={0} max={10} step={0.1} onChange={(x) => set({ cvss: x })} format={(x) => fmt(x, 1)} />
            </div>
          </div>
          <p className="mt-5 max-w-[56ch] text-[15px] leading-snug text-muted lg:hidden">
            Plazo de remediación: {sla}. {resultado}.
          </p>
        </div>
      </div>
    </section>
  )
}

/* ───────────────────────── Qué incluye ───────────────────────── */

const MODULOS: Array<[string, string]> = [
  ['Resumen ejecutivo', 'Tendencia, cumplimiento de SLA y tiempo medio de remediación, calculados con una sola fuente de cifras.'],
  ['Activos e importación', 'Cargue hallazgos desde CSV o desde un escaneo Nessus. Se previsualizan antes de confirmar y un host desconocido queda marcado “Por completar”.'],
  ['Catálogo KEV y vulnerabilidades', 'Filtre por producto, ransomware o banda de riesgo y vea qué activos expone cada CVE.'],
  ['Alertas y tickets', 'Un ticket por coincidencia nueva, con plazo. Resolverlo mitiga el hallazgo; aceptar el riesgo lo deja registrado.'],
  ['Asistente de IA', 'Responde preguntas y redacta el enriquecimiento de cada ticket usando solo datos recuperados del propio sistema.'],
  ['Reportes', 'Exporte a PDF, Word o Excel, con resumen opcional redactado por IA. Cada exportación queda en la bitácora.'],
  ['Bitácora', 'Registro de solo añadir con hash encadenado: nadie puede editarlo ni borrarlo.'],
  ['Usuarios y roles', 'Permisos por módulo y acción, validados en el servidor. La interfaz solo oculta lo que no corresponde.'],
]

const GRUPOS: Array<[string, number[]]> = [
  ['Para detectar', [0, 1, 2]],
  ['Para actuar', [3, 4, 5]],
  ['Para controlar', [6, 7]],
]

function Incluye() {
  return (
    <section className={`${gutter} ${section}`}>
      <div className="grid gap-12 lg:grid-cols-12 lg:gap-x-6">
        <Reveal className="lg:col-span-5">
          <div className="lg:sticky lg:top-24">
            <h2 className={h2}>Todo en un solo panel</h2>
            <div className="mt-8 max-w-[520px]">
              <RankingFragment />
            </div>
          </div>
        </Reveal>
        <div className="space-y-14 lg:col-span-7">
          {GRUPOS.map(([g, idx]) => (
            <div key={g}>
              <Reveal>
                <h3 className="text-[clamp(26px,2.8vw,40px)] font-semibold leading-tight tracking-[-0.01em]">{g}</h3>
              </Reveal>
              <div className="mt-6 grid gap-x-10 gap-y-9 sm:grid-cols-2">
                {idx.map((i, k) => (
                  <Reveal key={MODULOS[i][0]} delay={k * 0.06}>
                    <h4 className="text-[clamp(19px,1.8vw,24px)] font-semibold leading-tight">{MODULOS[i][0]}</h4>
                    <p className="mt-2 max-w-[36ch] text-[17px] leading-relaxed">{MODULOS[i][1]}</p>
                  </Reveal>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ───────────────────────── Confianza ───────────────────────── */

const REGLAS: Array<[string, string]> = [
  ['La detección es determinista', 'El cruce, el puntaje y el plazo son código y pandas, no un modelo. La IA nunca decide qué es crítico.'],
  ['La IA solo cita lo que existe', 'Cada respuesta parte de datos recuperados, valida CVE, hosts y enlaces, y queda registrada en una bitácora de IA.'],
  ['Nada se borra en silencio', 'La bitácora solo se añade y encadena sus hashes. Cambiar una fila rompe la cadena.'],
  ['Cada parte tiene un solo trabajo', 'n8n orquesta pero nunca escribe en la base de datos: llama a una API interna con clave de servicio.'],
]

function Confianza() {
  return (
    <section className="bg-ink text-bg">
      <div className={`${gutter} ${section}`}>
        <Reveal>
          <h2 className={`${h2} max-w-[16ch]`}>Una decisión que puede explicar</h2>
        </Reveal>
        <div className="mt-[clamp(48px,8vw,120px)] grid gap-x-10 gap-y-14 md:grid-cols-2">
          {REGLAS.map(([t, d], i) => (
            <Reveal key={t} delay={(i % 2) * 0.07}>
              <h3 className="text-[clamp(26px,3vw,44px)] font-semibold leading-[1.05] tracking-[-0.01em]">{t}</h3>
              <p className="mt-3 max-w-[40ch] text-[17px] leading-relaxed">{d}</p>
            </Reveal>
          ))}
        </div>
        <Radar className="mt-[clamp(48px,8vw,120px)]" />
      </div>
    </section>
  )
}

/* ───────────────────────── Preguntas ───────────────────────── */

const FAQ: Array<[string, string]> = [
  ['¿En qué se diferencian CVSS, EPSS y KEV?', 'CVSS mide la gravedad técnica de una falla. EPSS estima la probabilidad de que se explote en 30 días. KEV confirma que ya se explota. El radar usa los tres y deja que KEV domine, porque un ataque real pesa más que una probabilidad.'],
  ['¿La IA decide qué vulnerabilidades son críticas?', 'No. La detección, el puntaje y el plazo son lógica determinista. La IA solo redacta resúmenes y responde preguntas con datos que el sistema recupera, y cada interacción queda registrada.'],
  ['¿De dónde salen los datos y cada cuánto se actualizan?', 'Del catálogo público KEV de CISA y de los valores públicos de EPSS de FIRST. Un flujo de n8n los descarga y cruza cada día; también puede lanzarlo a mano con “Ejecutar ahora”.'],
  ['¿Cómo cargo mis activos y hallazgos?', 'Importando un CSV o un archivo .nessus. Primero se previsualiza sin escribir nada y luego se confirma. Si el escáner trae un host que no está en el inventario, se crea como activo “Por completar”.'],
  ['¿Puedo cambiar la fórmula y los plazos?', 'Sí, desde Configuración. Los pesos, las bandas y los plazos se versionan, y recalcular no gasta las coincidencias nuevas del día ni altera los hallazgos ya cerrados.'],
  ['¿Quién puede ver o modificar cada cosa?', 'Cada usuario tiene un rol con permisos por módulo y acción, validados en el servidor. Las exportaciones y los cambios sensibles quedan en la bitácora de solo añadir.'],
]

function Preguntas() {
  return (
    <section id="preguntas" className={`scroll-mt-14 ${gutter} ${section}`}>
      <Reveal>
        <h2 className="max-w-[18ch] text-[clamp(40px,5.5vw,88px)] font-semibold leading-[1] tracking-[-0.01em]">Preguntas frecuentes</h2>
      </Reveal>
      <div className="mt-16 grid md:grid-cols-12 md:gap-x-6">
        <div className="space-y-2 md:col-span-8 md:col-start-5">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group -mx-2 rounded-[28px] px-2 transition-colors duration-200 ease-out open:bg-sunken md:-mx-6 md:px-6">
              <summary className="flex min-h-[56px] cursor-pointer list-none items-center justify-between gap-6 rounded-[28px] py-4 text-[clamp(19px,1.7vw,24px)] leading-snug [&::-webkit-details-marker]:hidden">
                {q}
                <CaretDown className="shrink-0 transition-transform duration-200 ease-out group-open:rotate-180" weight="bold" aria-hidden />
              </summary>
              <p className="faq-answer max-w-[48ch] pb-6 text-[17px] leading-relaxed">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ───────────────────────── Cierre ───────────────────────── */

function Cierre() {
  const { user } = useAuth()
  return (
    <section className={`${gutter} bg-sunken ${section}`}>
      <Reveal>
        <h2 className="text-[clamp(40px,6vw,96px)] font-semibold leading-[1.12] tracking-[-0.01em]">
          Empiece hoy por lo urgente.{' '}
          <Link to={user ? '/resumen' : '/login'} className="inline-flex h-[1.1em] items-center rounded-full bg-accent px-[0.4em] align-baseline text-accent-ink transition-[transform,opacity] duration-150 ease-out hover:opacity-90 active:scale-[0.98]">
            {user ? 'Ir al panel' : 'Ingresar'}
          </Link>
        </h2>
        <p className="mt-6 max-w-[56ch] text-[16px]">
          El acceso es con una cuenta que le asigne su administrador. Los datos que ve aquí son de demostración.
          {CONTACT && (
            <>
              {' '}
              ¿Aún no tiene cuenta?{' '}
              <a href={`mailto:${CONTACT}?subject=Demostración del Radar KEV/EPSS`} className="underline underline-offset-4 transition-colors hover:text-link">
                Pida una demostración
              </a>
              .
            </>
          )}
        </p>
      </Reveal>
    </section>
  )
}

function Pie() {
  const { user } = useAuth()
  return (
    <footer className="bg-ink text-bg">
      <div className={`${gutter} flex min-h-[60svh] flex-col justify-between gap-16 py-10`}>
        <div className="grid gap-4 text-[15px] md:grid-cols-[1fr_1fr_1fr_auto] md:gap-8">
          <p className="max-w-[30ch]">Radar de explotación activa: cruza a diario el inventario propio con CISA KEV y FIRST EPSS.</p>
          <p className="max-w-[30ch]">Zona horaria de la interfaz: America/Lima. La base de datos guarda UTC.</p>
          <p className="max-w-[30ch]">Los datos de CISA KEV y de EPSS (FIRST) son públicos y pertenecen a sus autores.</p>
          <a href="#inicio" className="underline underline-offset-4">
            Volver arriba
          </a>
        </div>
        <div>
          <Link to={user ? '/resumen' : '/login'} className="block text-[clamp(44px,8vw,140px)] font-semibold leading-[0.95] tracking-[-0.01em] transition-opacity duration-150 hover:opacity-85">
            {user ? 'Ir al panel' : 'Ingresar al radar'} →
          </Link>
          <p className="mt-10 max-w-[70ch] text-[14px]">Fotografía vía Wikimedia Commons: “Vitino, RT-70 deep space radio telescope” de Vyacheslav Argenberg (CC BY 4.0), en escala de grises con tono azul.</p>
          <div className="mt-6 grid gap-1 text-[14px] md:grid-cols-3">
            <span>
              <a className="underline underline-offset-4" href="#fundamentos">Fundamentos</a>
              {' · '}
              <a className="underline underline-offset-4" href="#calculadora">Calculadora</a>
              {' · '}
              <a className="underline underline-offset-4" href="#preguntas">Preguntas</a>
            </span>
            <span className="md:text-center">Radar KEV/EPSS</span>
            <span className="md:text-right">Lima · {new Date().getFullYear()}</span>
          </div>
        </div>
      </div>
    </footer>
  )
}

export default function Landing() {
  useEffect(() => {
    const prev = document.title
    document.title = 'Radar KEV/EPSS: parche primero lo que ya se explota'
    return () => {
      document.title = prev
    }
  }, [])
  return (
    <div className="bg-bg text-ink [font-size:16px]">
      <a href="#contenido" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-surface focus:p-2">
        Saltar al contenido
      </a>
      <Header />
      <main id="contenido">
        <Hero />
        <Fundamentos />
        <Contraste />
        <Funcionamiento />
        <Calculadora />
        <Incluye />
        <Confianza />
        <Preguntas />
        <Cierre />
      </main>
      <Pie />
    </div>
  )
}
