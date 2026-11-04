import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowUp, CircleNotch, Crosshair, Eye, EyeSlash, LockKey, Warning } from '@phosphor-icons/react'
import { useState, type KeyboardEvent } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate } from 'react-router-dom'
import { z } from 'zod'

import { Button, Field, Input } from '../components/ui'
import { Photo } from '../landing/Photo'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

const schema = z.object({
  email: z.string().min(1, 'Ingrese su correo').regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, 'Correo no válido'),
  password: z.string().min(1, 'Ingrese su contraseña'),
})
type Form = z.infer<typeof schema>

/** Mensaje de error del ingreso. Es genérico a propósito: no revela si el correo existe. */
export function loginErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 423) return 'La cuenta está bloqueada temporalmente por intentos fallidos. Intente en 15 minutos o pida a un administrador que la desbloquee.'
    if (e.status === 429) return 'Demasiados intentos. Espere un minuto e intente de nuevo.'
    if (e.status === 401) return 'Correo o contraseña incorrectos.'
  }
  return 'No se pudo iniciar sesión. Revise su conexión e intente de nuevo.'
}

/** Lado visual: el radar sobre negro, fundido en los bordes. En móvil es una franja arriba. */
function Visual() {
  return (
    <aside className="dark relative flex min-h-[190px] items-end overflow-hidden bg-surface p-5 text-ink md:p-8 lg:min-h-screen lg:items-end lg:p-12" aria-label="Radar KEV/EPSS">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{ maskImage: 'radial-gradient(ellipse 70% 70% at 50% 45%, #000 40%, transparent 100%)', WebkitMaskImage: 'radial-gradient(ellipse 70% 70% at 50% 45%, #000 40%, transparent 100%)' }}
      >
        <Photo
          name="hero-1-baborak"
          alt=""
          sizes="(min-width: 1024px) 50vw, 100vw"
          priority
          className="size-full object-[50%_70%]"
        />
      </div>
      <div className="relative z-10">
        <p className="mb-2 flex items-center gap-2 text-[14px] font-semibold">
          <Crosshair size={18} weight="bold" aria-hidden />
          Radar KEV/EPSS
        </p>
        <p className="max-w-[11em] text-balance text-[clamp(26px,3.6vw,48px)] font-semibold uppercase leading-[1.06] tracking-[-0.009em]">Parche primero lo que ya explotan</p>
      </div>
    </aside>
  )
}

export default function Login() {
  const { user, login } = useAuth()
  const [error, setError] = useState<{ msg: string; locked: boolean } | null>(null)
  const [show, setShow] = useState(false)
  const [caps, setCaps] = useState(false)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema) })

  if (user) return <Navigate to="/resumen" replace />

  const watchCaps = (e: KeyboardEvent<HTMLInputElement>) => setCaps(e.getModifierState('CapsLock'))
  const pw = register('password')

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <Visual />
      <main className="grid place-items-center px-4 py-10 lg:px-12">
        <div className="w-full max-w-[360px]">
          <h1 className="text-[24px] font-semibold leading-tight">Iniciar sesión</h1>
          <p className="mt-1 text-[13px] text-muted">Use la cuenta que le asignó su administrador.</p>
          <form
            className="mt-6 space-y-4"
            noValidate
            onSubmit={handleSubmit(async (v) => {
              setError(null)
              try {
                await login(v.email, v.password)
              } catch (e) {
                setError({ msg: loginErrorMessage(e), locked: e instanceof ApiError && e.status === 423 })
              }
            })}
          >
            <Field label="Correo" error={errors.email?.message}>
              <Input type="email" autoComplete="username" autoFocus {...register('email')} />
            </Field>
            <Field label="Contraseña" error={errors.password?.message}>
              <div className="relative">
                <Input
                  type={show ? 'text' : 'password'}
                  autoComplete="current-password"
                  className="!pr-11"
                  {...pw}
                  onKeyDown={watchCaps}
                  onKeyUp={watchCaps}
                  onBlur={(e) => {
                    setCaps(false)
                    void pw.onBlur(e)
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                  aria-pressed={show}
                  className="absolute right-1 top-1/2 grid size-7 -translate-y-1/2 place-items-center rounded-full text-muted transition-[transform,background-color] duration-150 hover:bg-sunken hover:text-ink active:scale-[0.97] pointer-coarse:size-10"
                >
                  {show ? <EyeSlash size={17} /> : <Eye size={17} />}
                </button>
              </div>
              {caps && (
                <span role="status" className="mt-1.5 flex items-center gap-1 text-[12px] text-warn">
                  <ArrowUp size={13} weight="bold" aria-hidden />
                  Bloq Mayús está activado
                </span>
              )}
            </Field>
            {error && (
              <p role="alert" className="flex items-start gap-2 rounded-[10px] bg-danger-soft px-3 py-2.5 text-[13px] text-danger">
                {error.locked ? <LockKey size={16} weight="bold" className="mt-0.5 shrink-0" aria-hidden /> : <Warning size={16} weight="bold" className="mt-0.5 shrink-0" aria-hidden />}
                {error.msg}
              </p>
            )}
            <Button type="submit" variant="primary" className="w-full" disabled={isSubmitting} aria-busy={isSubmitting}>
              {isSubmitting && <CircleNotch size={15} weight="bold" className="animate-spin" aria-hidden />}
              {isSubmitting ? 'Ingresando…' : 'Ingresar'}
            </Button>
          </form>
          <Link to="/" className="mt-6 inline-block text-[13px] text-muted underline underline-offset-4 hover:text-ink">
            Volver al sitio
          </Link>
        </div>
      </main>
    </div>
  )
}
