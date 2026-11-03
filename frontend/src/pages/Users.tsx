import { zodResolver } from '@hookform/resolvers/zod'
import { Plus } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  Button, Dialog, EmptyState, ErrorState, Field, Input, PageHeader, Panel, Select, Skeleton,
  StatusBadge, td, th,
} from '../components/ui'
import { api } from '../lib/api'
import { useAuth, type User } from '../lib/auth'

interface UserList { items: User[]; total: number }
interface Role { id: number; name: string }

const PAGE = 25

const schema = z.object({
  full_name: z.string().min(2, 'Mínimo 2 caracteres').max(120),
  email: z.string().regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, 'Correo no válido'),
  password: z
    .string()
    .min(12, 'Mínimo 12 caracteres')
    .refine((p) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(p)).length >= 3, 'Combine al menos 3 de: minúsculas, mayúsculas, números y símbolos'),
  role_id: z.coerce.number().int().positive('Seleccione un rol'),
})
type Form = z.infer<typeof schema>

export default function Users() {
  const { can, user: me } = useAuth()
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState(false)

  const users = useQuery({
    queryKey: ['users', q, page],
    queryFn: () => api.get<UserList>('/users', { q, limit: PAGE, offset: page * PAGE }),
  })
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => api.get<Role[]>('/roles') })

  const refresh = () => qc.invalidateQueries({ queryKey: ['users'] })
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) => api.patch(`/users/${id}`, body),
    onSuccess: () => { toast.success('Usuario actualizado'); void refresh() },
    onError: (e: Error) => toast.error(e.message),
  })
  const unlock = useMutation({
    mutationFn: (id: string) => api.post(`/users/${id}/unlock`),
    onSuccess: () => { toast.success('Cuenta desbloqueada'); void refresh() },
    onError: (e: Error) => toast.error(e.message),
  })
  const create = useMutation({
    mutationFn: (v: Form) => api.post('/users', v),
    onSuccess: () => { toast.success('Usuario creado'); setOpen(false); reset(); void refresh() },
    onError: (e: Error) => toast.error(e.message),
  })
  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ resolver: zodResolver(schema) as never })

  const total = users.data?.total ?? 0
  return (
    <>
      <PageHeader
        title="Usuarios"
        subtitle="Cuentas de acceso y su rol. Los permisos se validan siempre en el servidor."
        actions={can('users', 'create') && <Button variant="primary" onClick={() => setOpen(true)}><Plus size={15} weight="bold" /> Nuevo usuario</Button>}
      />
      <div className="mb-3 max-w-xs">
        <Input placeholder="Buscar por nombre o correo" aria-label="Buscar usuarios" value={q} onChange={(e) => { setQ(e.target.value); setPage(0) }} />
      </div>
      <Panel className="overflow-x-auto">
        {users.isPending ? <Skeleton cols={5} /> : users.isError ? (
          <ErrorState message={users.error.message} onRetry={() => void users.refetch()} />
        ) : users.data.items.length === 0 ? (
          <EmptyState title="Sin resultados" hint={q ? 'Ningún usuario coincide con la búsqueda.' : 'Aún no hay usuarios.'} />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr><th className={th}>Nombre</th><th className={th}>Correo</th><th className={th}>Rol</th><th className={th}>Estado</th><th className={th}><span className="sr-only">Acciones</span></th></tr></thead>
            <tbody>
              {users.data.items.map((u) => (
                <tr key={u.id}>
                  <td className={`${td} font-medium`}>{u.full_name}</td>
                  <td className={`${td} font-mono text-[12px]`}>{u.email}</td>
                  <td className={td}>
                    {can('users', 'edit') && u.id !== me?.id ? (
                      <Select aria-label={`Rol de ${u.full_name}`} className="!h-7 !w-auto" value={roles.data?.find((r) => r.name === u.role)?.id ?? ''} onChange={(e) => patch.mutate({ id: u.id, body: { role_id: Number(e.target.value) } })}>
                        {roles.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </Select>
                    ) : u.role}
                  </td>
                  <td className={td}><StatusBadge kind={u.is_active ? 'ok' : 'neutral'}>{u.is_active ? 'Activo' : 'Inactivo'}</StatusBadge></td>
                  <td className={`${td} text-right whitespace-nowrap`}>
                    {can('users', 'edit') && <Button variant="ghost" onClick={() => unlock.mutate(u.id)}>Desbloquear</Button>}
                    {can('users', 'edit') && u.id !== me?.id && (
                      <Button variant="ghost" onClick={() => patch.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                        {u.is_active ? 'Desactivar' : 'Activar'}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      {total > PAGE && (
        <div className="mt-3 flex items-center justify-between text-[13px] text-muted">
          <span>{page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} de {total}</span>
          <div className="flex gap-2">
            <Button disabled={page === 0} onClick={() => setPage(page - 1)}>Anterior</Button>
            <Button disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Siguiente</Button>
          </div>
        </div>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} title="Nuevo usuario">
        <form className="space-y-3" noValidate onSubmit={handleSubmit((v) => create.mutate(v))}>
          <Field label="Nombre completo" error={errors.full_name?.message}><Input {...register('full_name')} /></Field>
          <Field label="Correo" error={errors.email?.message}><Input type="email" {...register('email')} /></Field>
          <Field label="Contraseña inicial" error={errors.password?.message}><Input type="password" autoComplete="new-password" {...register('password')} /></Field>
          <Field label="Rol" error={errors.role_id?.message}>
            <Select defaultValue="" {...register('role_id')}>
              <option value="" disabled>Seleccione…</option>
              {roles.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </Select>
          </Field>
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" onClick={() => setOpen(false)}>Cancelar</Button>
            <Button type="submit" variant="primary" disabled={create.isPending}>Crear usuario</Button>
          </div>
        </form>
      </Dialog>
    </>
  )
}
