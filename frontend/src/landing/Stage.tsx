// Portada y sección de destacados con la estructura de DESIGN.md (Layout): escenario negro, titular centrado en mayúsculas,
// producto flotando y pila de acción; después una banda Carbon con una baldosa fotográfica de 28 px y una métrica en verde.
import { Crosshair, Plus } from '@phosphor-icons/react'
import { motion, useReducedMotion } from 'motion/react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { useAuth } from '../lib/auth'
import { EpssFragment, InventoryFragment, KevFragment, RankingFragment, RunFragment, TicketFragment } from './Fragments'

const EASE = [0.23, 1, 0.32, 1] as const

// Botón de compra compacto de DESIGN.md: Purchase Blue, píldora, 12 px.
export const buy =
  'inline-flex items-center justify-center rounded-full bg-accent px-2.5 py-1 text-[12px] leading-4 text-accent-ink transition-[transform,opacity] duration-150 ease-out hover:opacity-90 active:scale-[0.97] pointer-coarse:min-h-[44px] pointer-coarse:px-4'

const VIEWS = [
  { label: 'Lista priorizada', caption: 'Lo ya explotado queda arriba de la lista.', node: <RankingFragment /> },
  { label: 'Ejecución diaria', caption: 'Cada día se cruza el catálogo con su inventario.', node: <RunFragment /> },
  { label: 'Ticket con plazo', caption: 'Cada coincidencia nueva abre un ticket con plazo.', node: <TicketFragment /> },
]

export function HeroStage({ contact }: { contact?: string }) {
  const { user } = useAuth()
  const reduce = useReducedMotion()
  const [step, setStep] = useState(0)

  return (
    <section id="inicio" className="dark bg-surface text-ink">
      <div className="mx-auto flex max-w-[1100px] flex-col items-center px-4 pb-[clamp(56px,8vw,96px)] pt-[clamp(40px,7vw,90px)] text-center md:px-8">
        <p className="flex items-center gap-2 text-[19px] font-semibold leading-[1.21] tracking-[0.012em]">
          <Crosshair size={22} weight="bold" aria-hidden />
          CISA KEV + FIRST EPSS
        </p>
        <h1 className="mt-4 max-w-[17ch] text-balance text-[clamp(34px,6vw,64px)] font-semibold uppercase leading-[1.06] tracking-[-0.009em]">
          Parche primero lo que ya explotan
        </h1>
        <p className="mt-5 max-w-[54ch] text-[17px] leading-[1.47] tracking-[-0.022em]">
          Cruza cada día su inventario con el catálogo KEV de CISA (las vulnerabilidades que ya se atacan) y con EPSS de FIRST (la probabilidad de que se ataquen), y le dice qué arreglar primero.
        </p>

        <div className="mt-[clamp(32px,5vw,56px)] w-full max-w-[760px]">
          <div className="grid text-left" role="img" aria-label="Ejemplo de la interfaz del radar con datos de demostración">
            {VIEWS.map((v, i) => (
              <motion.div
                key={v.label}
                className="col-start-1 row-start-1 self-center"
                aria-hidden
                initial={false}
                animate={{ opacity: i === step ? 1 : 0, y: reduce ? 0 : i === step ? 0 : 12 }}
                transition={{ duration: 0.25, ease: EASE }}
                style={{ pointerEvents: i === step ? 'auto' : 'none' }}
              >
                {v.node}
              </motion.div>
            ))}
          </div>
          <div role="group" aria-label="Ejemplos de la interfaz" className="mt-5 flex flex-wrap justify-center gap-2">
            {VIEWS.map((v, i) => (
              <button
                key={v.label}
                type="button"
                aria-pressed={i === step}
                onClick={() => setStep(i)}
                className={`min-h-[44px] rounded-[36px] px-4 text-[14px] tracking-[-0.016em] transition-[background-color,transform] duration-150 ease-out active:scale-[0.97] ${
                  i === step ? 'bg-ink text-surface' : 'bg-chip text-ink/80 hover:text-ink'
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-8 flex flex-col items-center gap-3">
          <Link to={user ? '/resumen' : '/login'} className={`${buy} !px-3 !py-1.5 !text-[14px] !leading-[18px] pointer-coarse:!px-5`}>
            {user ? 'Ir al panel' : 'Ingresar al radar'}
          </Link>
          <p className="max-w-[52ch] text-[14px] font-semibold leading-[1.29] tracking-[-0.016em]">
            {VIEWS[step].caption}
          </p>
          <p className="max-w-[52ch] text-[14px] leading-[1.29] tracking-[-0.016em] text-muted">
            Acceso con la cuenta que le asigne su administrador. Datos de demostración.
            {contact && (
              <>
                {' '}
                <a href={`mailto:${contact}?subject=Demostración del Radar KEV/EPSS`} className="text-link underline-offset-4 hover:underline">
                  Pedir una demostración
                </a>
              </>
            )}
          </p>
        </div>
      </div>
    </section>
  )
}

export function Highlights() {
  const reduce = useReducedMotion()
  return (
    <section id="destacados" className="dark scroll-mt-24 bg-bg text-ink">
      <div className="mx-auto max-w-[1100px] px-4 py-[clamp(56px,9vw,120px)] md:px-8">
        <h2 className="max-w-[18ch] text-[clamp(30px,4.4vw,48px)] font-semibold leading-none tracking-[-0.003em]">Se mide lo que se remedia, no lo que se detecta</h2>
        <motion.figure
          className="relative mt-10 flex min-h-[500px] flex-col justify-end overflow-hidden rounded-[28px] bg-surface md:min-h-[580px]"
          initial={reduce ? false : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '0px 0px -10% 0px' }}
          transition={{ duration: 0.4, ease: EASE }}
        >
          <img
            src="/fotos/radar-rt70.jpg"
            width={1920}
            height={1280}
            alt="Gran antena parabólica del radar planetario RT-70 bajo un cielo despejado, en blanco y negro"
            loading="lazy"
            decoding="async"
            className="absolute inset-0 size-full object-cover grayscale contrast-125"
          />
          <div className="absolute inset-0 bg-black/55" aria-hidden />
          <figcaption className="relative p-6 md:p-12">
            <p className="text-[clamp(52px,8vw,64px)] font-semibold leading-[1.06] tracking-[-0.009em] text-battery-green tabular-nums">
              94 %
              <span className="sr-only"> de cumplimiento de SLA</span>
            </p>
            <p className="mt-1 text-[19px] font-semibold leading-[1.21] tracking-[0.012em]" aria-hidden>
              de cumplimiento de SLA
            </p>
            <p className="mt-4 max-w-[46ch] text-[17px] leading-[25px] tracking-[-0.022em]">
              Cada hallazgo recibe un plazo según su banda de riesgo (de 15 a 180 días) o la fecha límite de CISA si está en KEV. El panel muestra cuántos se cierran a tiempo y el tiempo medio de remediación.
            </p>
            <p className="mt-4 text-[14px] leading-[1.29] text-ink/80">Cifra de demostración.</p>
          </figcaption>
        </motion.figure>
      </div>
    </section>
  )
}

const FEATURES = [
  { label: 'Priorización', text: 'Cada hallazgo recibe un puntaje de 0 a 100 que combina KEV, EPSS, CVSS y la criticidad del activo. Lo ya explotado queda arriba.', node: <RankingFragment /> },
  { label: 'Activos e importación', text: 'Cargue hallazgos desde CSV o desde un escaneo Nessus. Se previsualizan antes de confirmar y un host desconocido queda marcado “Por completar”.', node: <InventoryFragment /> },
  { label: 'Catálogo KEV y EPSS', text: 'Filtre por producto, ransomware o banda de riesgo y vea qué activos expone cada CVE.', node: <div className="space-y-3"><KevFragment /><EpssFragment /></div> },
  { label: 'Cruce diario', text: 'Cada día descarga el catálogo y los valores EPSS, los cruza con su inventario y abre un ticket por cada coincidencia nueva.', node: <RunFragment /> },
  { label: 'Alertas y tickets', text: 'Un ticket por coincidencia nueva, con plazo. Resolverlo mitiga el hallazgo; aceptar el riesgo lo deja registrado.', node: <TicketFragment /> },
]

export function CloseLook() {
  const reduce = useReducedMotion()
  const [sel, setSel] = useState(0)
  return (
    <section id="modulos" className="dark scroll-mt-24 bg-surface text-ink">
      <div className="mx-auto max-w-[1100px] px-4 py-[clamp(56px,9vw,120px)] md:px-8">
        <h2 className="max-w-[18ch] text-[clamp(30px,4.4vw,48px)] font-semibold leading-none tracking-[-0.003em]">Un vistazo de cerca</h2>
        <div className="mt-10 grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:items-stretch">
          <ul className="flex flex-col gap-2">
            {FEATURES.map((f, i) => (
              <li key={f.label}>
                <button
                  type="button"
                  aria-expanded={i === sel}
                  onClick={() => setSel(i)}
                  className={`flex min-h-[44px] w-full items-center gap-3 rounded-[36px] px-4 py-3 text-left text-[17px] font-semibold tracking-[-0.022em] transition-[background-color,transform] duration-150 ease-out active:scale-[0.99] ${i === sel ? 'bg-ink text-surface' : 'bg-control text-ink/80 hover:text-ink'}`}
                >
                  <span className={`grid size-6 shrink-0 place-items-center rounded-full border ${i === sel ? 'border-surface' : 'border-ink/60'}`} aria-hidden>
                    <Plus size={12} weight="bold" className={`transition-transform duration-200 ease-out ${i === sel && !reduce ? 'rotate-45' : ''}`} />
                  </span>
                  {f.label}
                </button>
                {i === sel && <p className="faq-answer px-4 pb-1 pt-3 text-[17px] leading-[25px] tracking-[-0.022em]">{f.text}</p>}
              </li>
            ))}
          </ul>
          <div className="relative min-h-[420px] overflow-hidden rounded-[28px] bg-surface ring-1 ring-line" role="img" aria-label={`Ejemplo de ${FEATURES[sel].label} con datos de demostración`}>
            {FEATURES.map((f, i) => (
              <motion.div
                key={f.label}
                className="absolute left-6 top-6 w-[125%] origin-top-left text-left"
                aria-hidden
                initial={false}
                animate={{ opacity: i === sel ? 1 : 0, scale: reduce ? 1 : i === sel ? 1 : 0.98 }}
                transition={{ duration: 0.25, ease: EASE }}
              >
                {f.node}
              </motion.div>
            ))}
          </div>
        </div>
        <p className="mt-4 text-[14px] text-muted">Datos de demostración.</p>
      </div>
    </section>
  )
}
