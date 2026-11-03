import { Plus } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button, Dialog, ErrorState, Field, Input, PageHeader, Panel, Skeleton, th, td } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ACTION_LABELS, moduleLabel } from '../lib/permissions'

interface Role { id: number; name: string; description: string; is_system: boolean; permissions: string[] }
interface Catalog { modules: string[]; actions: string[] }

export default function Roles() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const roles = useQuery({ queryKey: ['roles'], queryFn: () => api.get<Role[]>('/roles') })
  const catalog = useQuery({ queryKey: ['permissions'], queryFn: () => api.get<Catalog>('/permissions') })
  const [selected, setSelected] = useState<number | null>(null)
  const [drafts, setDrafts] = useState<Record<number, Set<string>>>({})
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')

  const role = roles.data?.find((r) => r.id === (selected ?? roles.data?.[0]?.id))
  // Borrador por rol, derivado: no hace falta sincronizarlo con un efecto.
  const draft = (role && drafts[role.id]) || new Set(role?.permissions ?? [])

  const save = useMutation({
    mutationFn: () => api.put(`/roles/${role!.id}/permissions`, { permissions: [...draft] }),
    onSuccess: () => { toast.success('Permisos guardados'); setDrafts({}); void qc.invalidateQueries({ queryKey: ['roles'] }) },
    onError: (e: Error) => toast.error(e.message),
  })
  const create = useMutation({
    mutationFn: () => api.post<Role>('/roles', { name, permissions: [] }),
    onSuccess: (r) => { toast.success('Rol creado'); setOpen(false); setName(''); setSelected(r.id); void qc.invalidateQueries({ queryKey: ['roles'] }) },
    onError: (e: Error) => toast.error(e.message),
  })
  const remove = useMutation({
    mutationFn: () => api.delete(`/roles/${role!.id}`),
    onSuccess: () => { toast.success('Rol eliminado'); setSelected(null); void qc.invalidateQueries({ queryKey: ['roles'] }) },
    onError: (e: Error) => toast.error(e.message),
  })

  const locked = role?.name === 'Administrador' // el servidor lo rechaza igualmente
  const editable = can('roles', 'edit') && !locked
  const toggle = (code: string) => {
    const next = new Set(draft)
    if (next.has(code)) next.delete(code); else next.add(code)
    if (role) setDrafts({ ...drafts, [role.id]: next })
  }
  const dirty = role ? [...draft].sort().join() !== [...role.permissions].sort().join() : false

  return (
    <>
      <PageHeader
        title="Roles y permisos"
        subtitle="Un rol es un conjunto de permisos por módulo. El Administrador no se puede editar para evitar quedarse sin acceso."
        actions={can('roles', 'create') && <Button onClick={() => setOpen(true)}><Plus size={15} weight="bold" /> Nuevo rol</Button>}
      />
      {roles.isPending || catalog.isPending ? <Panel><Skeleton cols={4} /></Panel> :
        roles.isError ? <Panel><ErrorState message={roles.error.message} onRetry={() => void roles.refetch()} /></Panel> :
        catalog.isError ? <Panel><ErrorState message={catalog.error.message} onRetry={() => void catalog.refetch()} /></Panel> : (
        <div className="grid gap-4 lg:grid-cols-[220px_1fr]">
          <nav aria-label="Roles" className="flex gap-1 overflow-x-auto lg:flex-col">
            {roles.data.map((r) => (
              <button key={r.id} onClick={() => setSelected(r.id)} aria-current={r.id === role?.id}
                className={`rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors duration-150 ${r.id === role?.id ? 'bg-sunken font-medium' : 'text-muted hover:bg-sunken hover:text-ink'}`}>
                {r.name}{r.is_system && <span className="ml-1.5 text-[11px] text-muted">sistema</span>}
              </button>
            ))}
          </nav>
          {role && (
            <Panel className="overflow-x-auto">
              <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
                <p className="text-[13px] text-muted">{role.description || 'Sin descripción'}</p>
                <div className="flex gap-2">
                  {can('roles', 'delete') && !role.is_system && <Button variant="danger" onClick={() => remove.mutate()}>Eliminar</Button>}
                  {editable && <Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Guardar cambios</Button>}
                </div>
              </div>
              <table className="w-full text-[13px]">
                <thead><tr><th className={th}>Módulo</th>{catalog.data.actions.map((a) => <th key={a} className={`${th} text-center`}>{ACTION_LABELS[a]}</th>)}</tr></thead>
                <tbody>
                  {catalog.data.modules.map((m) => (
                    <tr key={m}>
                      <td className={`${td} font-medium`}>{moduleLabel(m)}</td>
                      {catalog.data.actions.map((a) => {
                        const code = `${m}:${a}`
                        return (
                          <td key={a} className={`${td} text-center`}>
                            <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={draft.has(code)} disabled={!editable}
                              aria-label={`${moduleLabel(m)}: ${ACTION_LABELS[a]}`} onChange={() => toggle(code)} />
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </div>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} title="Nuevo rol">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
          <Field label="Nombre del rol"><Input value={name} minLength={3} required onChange={(e) => setName(e.target.value)} /></Field>
          <p className="text-[12px] text-muted">El rol se crea sin permisos; asígnelos luego en la matriz.</p>
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setOpen(false)}>Cancelar</Button>
            <Button type="submit" variant="primary" disabled={create.isPending}>Crear rol</Button>
          </div>
        </form>
      </Dialog>
    </>
  )
}
