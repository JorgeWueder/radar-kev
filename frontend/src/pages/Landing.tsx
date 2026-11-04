import '@fontsource/inter/400.css'
import '@fontsource/inter/600.css'
import { CaretDown, Crosshair } from '@phosphor-icons/react'
import { MotionConfig, motion, useMotionValue, useMotionValueEvent, useReducedMotion, useScroll, useSpring, useTransform, type MotionValue } from 'motion/react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import {
  BandTag,
  ComparisonFragment,
  RankingFragment,
} from '../landing/Fragments'
import { BayGravedad, BayInventario, BayKevEpss, BayRadar } from '../landing/Bays'
import { Photo } from '../landing/Photo'
import { buy, CloseLook, Highlights, HeroStage } from '../landing/Stage'
import { useAuth } from '../lib/auth'
import { bandOf, BAND_LABEL, PARAMS, riskScore, type ScoreInput } from '../lib/score'

const EASE = [0.23, 1, 0.32, 1] as const

// Correo para pedir una demostración: se define al compilar (VITE_CONTACT_EMAIL). Sin él, el botón no se muestra.
const CONTACT = (import.meta as { env?: Record<string, string | undefined> }).env?.VITE_CONTACT_EMAIL

const FLOAT = 'shadow-lg' // taste-skill-ignore: el menú flotante sí lleva sombra
const gutter = 'px-4 md:px-8'
const section = 'py-[clamp(56px,7vw,104px)]'
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
      viewport={{ once: true, margin: '0px 0px -4% 0px' }}
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
  const to = user ? '/resumen' : '/login'
  return (
    <header className="dark sticky top-0 z-30 bg-bg text-ink/80">
      <div className={`flex h-11 items-center justify-between ${gutter}`}>
        <a href="#inicio" className="flex items-center gap-2 text-[12px] leading-none tracking-[-0.01em] pointer-coarse:min-h-[44px]">
          <Crosshair size={16} weight="bold" aria-hidden />
          Radar de explotación activa
        </a>
        <Link to={to} className={buy}>
          {user ? 'Ir al panel' : 'Ingresar'}
        </Link>
      </div>
      <div className={`flex h-[52px] items-center justify-between ${gutter}`}>
        <a href="#inicio" className="text-[17px] font-semibold leading-[21px] tracking-[-0.022em]">
          Radar KEV/EPSS
        </a>
        <nav aria-label="Principal" className="flex items-center gap-5 text-[12px] leading-none tracking-[-0.01em]">
          <MobileMenu active={active} />
          {NAV.map(([label, href]) => (
            <a
              key={href}
              href={href}
              aria-current={active === href.slice(1) ? 'location' : undefined}
              className={`hidden py-1 transition-colors hover:text-ink lg:inline ${active === href.slice(1) ? 'text-ink underline decoration-1 underline-offset-[10px]' : ''}`}
            >
              {label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  )
}

function Contraste() {
  return (
    <section className={`${gutter} pb-[clamp(40px,6vw,88px)]`}>
      <Reveal>
        <h2 className="max-w-[18ch] text-[clamp(30px,3.6vw,52px)] font-semibold leading-[1.05] tracking-[-0.01em]">Dos CVE, dos prioridades</h2>
        <p className="mb-8 mt-4 max-w-[60ch] text-[17px] leading-relaxed">
          Con el mismo activo, uno es más grave en el papel y el otro ya está en el catálogo KEV. Primero se ordenan por gravedad (CVSS); después, por el puntaje del radar, y el que ya se explota pasa al primer lugar.
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

/* Línea del pipeline: se dibuja con el scroll (scaleX) y cada paso se enciende cuando la línea lo alcanza. */
function PipelineLine({ progress }: { progress: MotionValue<number> }) {
  const fill = useTransform(progress, [0.05, 0.85], [0, 1])
  return (
    <div className="relative mt-10 hidden h-3 md:block" aria-hidden>
      <div className="absolute left-1.5 right-[calc(25%+0.375rem)] top-1/2 h-px bg-ink/25" />
      <motion.div className="absolute left-1.5 right-[calc(25%+0.375rem)] top-1/2 h-px origin-left bg-ink" style={{ scaleX: fill }} />
      <div className="absolute inset-0 grid grid-cols-4">
        {STAGES.map((s, i) => (
          <PipelineDot key={s.time} fill={fill} at={i / (STAGES.length - 1)} />
        ))}
      </div>
    </div>
  )
}

function PipelineDot({ fill, at }: { fill: MotionValue<number>; at: number }) {
  const on = useTransform(fill, [Math.max(0, at - 0.04), at], [0, 1])
  return (
    <div className="relative size-3">
      <span className="absolute inset-0 rounded-full bg-ink/25" />
      <motion.span className="absolute inset-0 rounded-full bg-ink" style={{ opacity: on }} />
    </div>
  )
}

function Funcionamiento() {
  const reduce = useReducedMotion()
  const ref = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start 80%', 'center 40%'] })
  const done = useMotionValue(1)
  return (
    <section id="funcionamiento" className={`dark scroll-mt-24 bg-transparent ${gutter} ${section}`}>
      <div ref={ref} className="relative overflow-hidden rounded-[28px] bg-surface p-6 text-ink md:p-12">
        <Photo name="fiber-1-muller" alt="Haces de fibra óptica con puntas luminosas de colores sobre fondo oscuro" sizes="(min-width: 1100px) 1300px, 100vw" className="absolute inset-0 size-full" />
        <div className="absolute inset-0 bg-black/70" aria-hidden />
        <div className="relative">
          <Reveal>
            <h2 className="max-w-[14ch] text-[clamp(44px,6vw,96px)] font-semibold leading-[0.98] tracking-[-0.01em]">Cada día, sin que nadie lo pida</h2>
          </Reveal>
          <PipelineLine progress={reduce ? done : scrollYProgress} />
          <div className="mt-4 grid gap-[6px] md:grid-cols-4 md:mt-4" data-ui>
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
        </div>
      </div>
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

/* Puntaje de la calculadora: el número y el gauge semicircular transicionan suavemente entre valores. */
function ScoreGauge({ score, band }: { score: number; band: ReturnType<typeof bandOf> }) {
  const reduce = useReducedMotion()
  const mv = useSpring(score, { stiffness: 110, damping: 26, mass: 0.9 })
  const [shown, setShown] = useState(Math.round(score))
  const arc = useTransform(mv, (v) => Math.min(1, Math.max(0, v / 100)))
  useEffect(() => {
    if (reduce) mv.jump(score)
    else mv.set(score)
  }, [score, reduce, mv])
  useMotionValueEvent(mv, 'change', (v) => setShown(Math.round(v)))
  return (
    <div>
      <div className="relative w-full max-w-[220px] lg:max-w-[420px]">
        <svg viewBox="0 0 200 108" className="w-full" aria-hidden>
          <path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="currentColor" strokeOpacity="0.18" strokeWidth="10" strokeLinecap="round" />
          <motion.path d="M 10 100 A 90 90 0 0 1 190 100" fill="none" stroke="currentColor" strokeWidth="10" strokeLinecap="round" style={{ pathLength: arc }} />
        </svg>
        <p className="absolute inset-x-0 bottom-0 flex items-baseline justify-center gap-1 font-semibold leading-[0.85] tabular-nums tracking-[-0.01em]" aria-hidden>
          <span className="text-[clamp(44px,6.5vw,96px)]">{shown}</span>
          <span className="text-[clamp(16px,2vw,28px)] text-muted">/100</span>
        </p>
      </div>
      <p className="mt-3 text-[18px]" aria-live="polite" aria-atomic>
        <BandTag band={band} />
        <span className="sr-only">
          {Math.round(score)} de 100, {BAND_LABEL[band]}
        </span>
      </p>
    </div>
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
    <section id="calculadora" className="scroll-mt-24 bg-sunken">
      <div className={`${gutter} flex flex-col gap-8 py-[clamp(56px,8vw,120px)] lg:grid lg:grid-cols-2 lg:gap-x-16`}>
        <div className="sticky top-24 z-10 -mx-4 bg-sunken px-4 py-3 lg:static lg:col-start-2 lg:row-start-1 lg:mx-0 lg:p-0">
          <div className="lg:sticky lg:top-32">
            <ScoreGauge score={score} band={band} />
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
          <div className="lg:sticky lg:top-32">
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
      <Reveal className="mt-[clamp(40px,6vw,80px)]">
        <figure className="dark relative flex min-h-[clamp(320px,40vw,480px)] flex-col justify-end overflow-hidden rounded-[28px] bg-surface text-ink">
          <Photo name="soc-1-kostyuk" alt="Analista frente a varias pantallas en un centro de operaciones de seguridad, en blanco y negro" sizes="(min-width: 1100px) 1300px, 100vw" className="absolute inset-0 size-full" />
          <div className="absolute inset-0 bg-black/55" aria-hidden />
          <figcaption className="relative max-w-[52ch] p-6 md:p-12">
            <h3 className="text-[clamp(28px,3.4vw,48px)] font-semibold leading-none tracking-[-0.003em]">{MODULOS[3][0]}</h3>
            <p className="mt-4 text-[17px] leading-[25px] tracking-[-0.022em]">{MODULOS[3][1]}</p>
          </figcaption>
        </figure>
      </Reveal>
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

/* Bitácora: bloques encadenados por hash. Al pasar el cursor (o enfocar) sobre uno, se "altera" y la cadena se rompe desde ahí. Ejemplo ilustrativo. */
const CHAIN = [
  { what: 'Importación de hallazgos', hash: '3fa9c1', bad: '7b02e4' },
  { what: 'Cruce diario con KEV y EPSS', hash: 'b21c58', bad: 'e9d0a3' },
  { what: 'Ticket resuelto', hash: '7de0f6', bad: '41c7b9' },
  { what: 'Exportación de reporte', hash: 'c85a2d', bad: '0aa5f1' },
  { what: 'Cambio de configuración', hash: '19f4b7', bad: 'd36c80' },
]

function Bitacora() {
  const [alt, setAlt] = useState<number | null>(null)
  return (
    <div className="dark mt-[clamp(32px,5vw,72px)] rounded-[28px] bg-surface p-5 text-ink md:p-8">
      <h3 className="text-[clamp(22px,2.4vw,32px)] font-semibold leading-tight tracking-[-0.003em]">Una cadena que no se puede reescribir</h3>
      <p className="mt-2 max-w-[60ch] text-[15px] leading-snug text-muted">
        Cada registro guarda el hash del anterior. Pase el cursor o enfoque un bloque para simular una alteración: la cadena se rompe desde ahí. Ejemplo ilustrativo.
      </p>
      <ol className="mt-6 grid gap-3 md:grid-cols-5" onMouseLeave={() => setAlt(null)}>
        {CHAIN.map((b, i) => {
          const broken = alt !== null && i >= alt
          const self = alt === i
          return (
            <motion.li key={b.hash} initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '0px 0px -4% 0px' }} transition={{ duration: 0.5, ease: EASE, delay: i * 0.08 }}>
              <button
                type="button"
                onMouseEnter={() => setAlt(i)}
                onFocus={() => setAlt(i)}
                onBlur={() => setAlt(null)}
                onClick={() => setAlt((a) => (a === i ? null : i))}
                aria-pressed={self}
                className="relative block min-h-[44px] w-full overflow-hidden rounded-[20px] bg-control p-4 text-left"
              >
                <span aria-hidden className={`pointer-events-none absolute inset-0 rounded-[20px] bg-danger-soft ring-1 ring-danger transition-opacity duration-500 ease-out ${broken ? 'opacity-100' : 'opacity-0'}`} />
                <span className="relative block text-[12px] text-muted">Bloque {i + 1}</span>
                <span className="relative mt-1 block text-[15px] font-semibold leading-snug">{b.what}</span>
                <span className="relative mt-3 block font-mono text-[12px]">
                  <span className="text-muted">hash </span>
                  <span className={broken ? 'text-danger' : ''}>{self ? b.bad : b.hash}</span>
                </span>
                <span className="relative block font-mono text-[12px]">
                  <span className="text-muted">previo </span>
                  <span className={broken && !self ? 'text-danger' : ''}>{i === 0 ? '000000' : CHAIN[i - 1].hash}</span>
                </span>
                <span className={`relative mt-2 block text-[12px] font-semibold ${broken ? 'text-danger' : 'text-muted'}`}>
                  {self ? 'Contenido alterado' : broken ? 'Cadena rota' : 'Íntegro'}
                </span>
              </button>
            </motion.li>
          )
        })}
      </ol>
    </div>
  )
}

function Confianza() {
  return (
    <section className="bg-ink text-bg">
      <div className={`${gutter} ${section}`}>
        <Reveal>
          <h2 className={`${h2} max-w-[16ch]`}>Una decisión que puede explicar</h2>
        </Reveal>
        <div className="mt-[clamp(32px,5vw,72px)] grid gap-x-10 gap-y-14 md:grid-cols-2">
          {REGLAS.map(([t, d], i) => (
            <Reveal key={t} delay={(i % 2) * 0.07}>
              <h3 className="text-[clamp(26px,3vw,44px)] font-semibold leading-[1.05] tracking-[-0.01em]">{t}</h3>
              <p className="mt-3 max-w-[40ch] text-[17px] leading-relaxed">{d}</p>
            </Reveal>
          ))}
        </div>
        <Bitacora />
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
    <section id="preguntas" className={`scroll-mt-24 ${gutter} ${section}`}>
      <Reveal>
        <h2 className="max-w-[18ch] text-[clamp(40px,5.5vw,88px)] font-semibold leading-[1] tracking-[-0.01em]">Preguntas frecuentes</h2>
      </Reveal>
      <div className="mt-10 grid md:grid-cols-12 md:gap-x-6">
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

/* ───────────────────────── Información (baldosas blancas) ───────────────────────── */

const INFO: Array<{ title: string; body: string; link: [string, string]; external?: boolean }> = [
  { title: 'Fuentes públicas', body: 'El catálogo KEV lo publica CISA y los valores EPSS, FIRST. El radar solo los descarga y los cruza con su inventario.', link: ['Ver el catálogo KEV de CISA', 'https://www.cisa.gov/known-exploited-vulnerabilities-catalog'], external: true },
  { title: 'Una fórmula que puede revisar', body: 'El puntaje combina KEV, EPSS, percentil, CVSS y la criticidad del activo con pesos configurables y versionados.', link: ['Probar la calculadora', '#calculadora'] },
  { title: 'Probabilidad, no certeza', body: 'EPSS estima de 0 a 100 % la probabilidad de explotación en 30 días y se actualiza a diario.', link: ['Conocer EPSS de FIRST', 'https://www.first.org/epss/'], external: true },
]

function Informacion() {
  return (
    <section className={`light bg-bg text-ink ${gutter} pb-[clamp(48px,8vw,96px)]`}>
      <div className="mx-auto grid max-w-[1100px] gap-6 md:grid-cols-3">
        {INFO.map((t, i) => (
          <Reveal key={t.title} delay={i * 0.06}>
            <article className="flex h-full flex-col rounded-[28px] bg-surface p-6 text-[#1d1d1f]">
              <h3 className="text-[21px] font-semibold leading-[1.19] tracking-[0.011em]">{t.title}</h3>
              <p className="mt-3 text-[17px] leading-[1.47] tracking-[-0.022em]">{t.body}</p>
              <a
                href={t.link[1]}
                {...(t.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
                className="mt-auto inline-flex min-h-[44px] items-end pt-4 text-[17px] text-link hover:underline"
              >
                {t.link[0]}
                {t.external && <span className="sr-only"> (se abre en otra pestaña)</span>}
              </a>
            </article>
          </Reveal>
        ))}
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
    <footer className="light bg-bg text-ink">
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
          <p className="mt-10 max-w-[70ch] text-[14px]">Fotos: Jan Baborák, Bernd Dittrich, Tyler, Denny Müller, Tasha Kostyuk vía Unsplash.</p>
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
    <MotionConfig reducedMotion="user">
    <div className="landing-font bg-bg text-ink [font-size:16px]">
      <a href="#contenido" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:bg-surface focus:p-2">
        Saltar al contenido
      </a>
      <Header />
      <main id="contenido">
        <HeroStage contact={CONTACT} />
        <Highlights />
        <CloseLook />
        <BayRadar />
        <BayGravedad />
        <BayKevEpss />
        <BayInventario />
        <Contraste />
        <Funcionamiento />
        <Calculadora />
        <Incluye />
        <Confianza />
        <Preguntas />
        <Informacion />
        <Cierre />
      </main>
      <Pie />
    </div>
    </MotionConfig>
  )
}
