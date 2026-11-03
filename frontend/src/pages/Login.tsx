import { zodResolver } from '@hookform/resolvers/zod'
import { Crosshair } from '@phosphor-icons/react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate } from 'react-router-dom'
import { z } from 'zod'

import { Button, Field, Input } from '../components/ui'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

const schema = z.object({
  email: z.string().min(1, 'Ingrese su correo').regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, 'Correo no válido'),
  password: z.string().min(1, 'Ingrese su contraseña'),
})
type Form = z.infer<typeof schema>

export function loginErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 423) return 'La cuenta está bloqueada temporalmente por intentos fallidos. Intente en 15 minutos.'
    if (e.status === 429) return 'Demasiados intentos. Espere un minuto e intente de nuevo.'
    if (e.status === 401) return 'Credenciales inválidas.'
  }
  return 'No se pudo iniciar sesión. Revise su conexión e intente de nuevo.'
}

export default function Login() {
  const { user, login } = useAuth()
  const [error, setError] = useState('')
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Form>({ resolver: zodResolver(schema) })

  if (user) return <Navigate to="/resumen" replace />

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-[340px]">
        <div className="mb-5 flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-md bg-accent text-accent-ink" aria-hidden>
            <Crosshair size={22} weight="bold" />
          </span>
          <div className="leading-tight">
            <div className="text-[17px] font-semibold">Radar KEV/EPSS</div>
            <div className="text-[12px] text-muted">Inicie sesión para continuar</div>
          </div>
        </div>
        <form
          className="space-y-3 rounded-lg border border-line bg-surface p-5"
          noValidate
          onSubmit={handleSubmit(async (v) => {
            setError('')
            try {
              await login(v.email, v.password)
            } catch (e) {
              setError(loginErrorMessage(e))
            }
          })}
        >
          <Field label="Correo" error={errors.email?.message}>
            <Input type="email" autoComplete="username" autoFocus {...register('email')} />
          </Field>
          <Field label="Contraseña" error={errors.password?.message}>
            <Input type="password" autoComplete="current-password" {...register('password')} />
          </Field>
          {error && (
            <p role="alert" className="rounded-md bg-danger-soft px-2.5 py-2 text-[13px] text-danger">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? 'Ingresando…' : 'Ingresar'}
          </Button>
        </form>
      </div>
    </div>
  )
}
