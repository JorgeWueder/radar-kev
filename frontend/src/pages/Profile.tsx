import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Button, Field, Input, PageHeader, Panel, Select } from '../components/ui'
import { api } from '../lib/api'
import { useAuth, type User } from '../lib/auth'

const schema = z
  .object({
    current_password: z.string().min(1, 'Ingrese su contraseña actual'),
    new_password: z
      .string()
      .min(12, 'Mínimo 12 caracteres')
      .refine((p) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length >= 3, 'Combine al menos 3 de: minúsculas, mayúsculas, números y símbolos'),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'Las contraseñas no coinciden' })
type Form = z.infer<typeof schema>

export default function Profile() {
  const { user, setUser, logout } = useAuth()
  const [saving, setSaving] = useState(false)
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ resolver: zodResolver(schema) })

  const changePassword = async (v: Form) => {
    setSaving(true)
    try {
      await api.put('/auth/me/password', { current_password: v.current_password, new_password: v.new_password })
      toast.success('Contraseña actualizada. Vuelva a iniciar sesión.')
      reset()
      await logout() // el servidor revoca las demás sesiones
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }
  const setDensity = async (density: string) => {
    try { setUser(await api.put<User>('/auth/me/preferences', { density })) } catch (e) { toast.error((e as Error).message) }
  }

  return (
    <>
      <PageHeader title="Mi perfil" subtitle="Datos de la cuenta y preferencias personales." />
      <div className="grid max-w-3xl gap-4 md:grid-cols-2">
        <Panel className="space-y-2 p-4">
          <h2 className="text-[14px] font-semibold">Cuenta</h2>
          <dl className="grid grid-cols-[90px_1fr] gap-y-1.5 text-[13px]">
            <dt className="text-muted">Nombre</dt><dd>{user?.full_name}</dd>
            <dt className="text-muted">Correo</dt><dd className="font-mono text-[12px]">{user?.email}</dd>
            <dt className="text-muted">Rol</dt><dd>{user?.role}</dd>
            <dt className="text-muted">Permisos</dt><dd>{user?.permissions.length}</dd>
          </dl>
          <div className="pt-2">
            <Field label="Densidad de tablas">
              <Select value={user?.preferences.density ?? 'comfortable'} onChange={(e) => void setDensity(e.target.value)}>
                <option value="comfortable">Cómoda</option><option value="compact">Compacta</option>
              </Select>
            </Field>
          </div>
        </Panel>
        <Panel className="p-4">
          <h2 className="mb-3 text-[14px] font-semibold">Cambiar contraseña</h2>
          <form className="space-y-3" noValidate onSubmit={handleSubmit(changePassword)}>
            <Field label="Contraseña actual" error={errors.current_password?.message}><Input type="password" autoComplete="current-password" {...register('current_password')} /></Field>
            <Field label="Nueva contraseña" error={errors.new_password?.message}><Input type="password" autoComplete="new-password" {...register('new_password')} /></Field>
            <Field label="Confirmar nueva contraseña" error={errors.confirm?.message}><Input type="password" autoComplete="new-password" {...register('confirm')} /></Field>
            <Button type="submit" variant="primary" disabled={saving}>Actualizar contraseña</Button>
          </form>
        </Panel>
      </div>
    </>
  )
}
