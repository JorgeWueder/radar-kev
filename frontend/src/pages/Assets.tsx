import { zodResolver } from '@hookform/resolvers/zod'
import { DownloadSimple, Plus } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  Button, Dialog, EmptyState, ErrorState, Field, Input, PageHeader, Panel, Select, Skeleton,
  StatusBadge, td, th,
} from '../components/ui'
import { api, download } from '../lib/api'
import { useAuth, type User } from '../lib/auth'
import { ASSET_TYPE, CRITICALITY, ENVIRONMENT, criticalityKind } from '../lib/labels'

interface Asset {
  id: string; hostname: string; ip: string | null; asset_type: string; os: string | null
  owner_id: string | null; owner_name: string | null; criticality: number; environment: string
  is_active: boolean; auto_created: boolean
}
interface AssetList { items: Asset[]; total: number }

const PAGE = 50
const schema = z.object({
  hostname: z.string().min(1, 'Requerido').regex(/^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$/, 'Solo letras, números, punto, guion'),
  ip: z.string().refine((v) => v === '' || /^[0-9a-fA-F:.]+$/.test(v), 'IP no válida'),
  asset_type: z.string(),
  os: z.string().max(120),
  owner_id: z.string(),
  criticality: z.coerce.number().int().min(1).max(4),
  environment: z.string(),
})
type Form = z.infer<typeof schema>

export default function Assets() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [f, setF] = useState({ q: '', environment: '', criticality: '' })
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState<Asset | 'new' | null>(null)

  const params = { ...f, limit: PAGE, offset: page * PAGE }
  const list = useQuery({ queryKey: ['assets', params], queryFn: () => api.get<AssetList>('/assets', params) })
  const users = useQuery({ queryKey: ['users', '', 0, 'all'], queryFn: () => api.get<{ items: User[] }>('/users', { limit: 200 }), enabled: can('users', 'view') })

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => { setF({ ...f, [k]: e.target.value }); setPage(0) }
  const refresh = () => qc.invalidateQueries({ queryKey: ['assets'] })

  const { register, handleSubmit, reset, formState: { errors } } = useForm<Form>({ resolver: zodResolver(schema) as never })
  const open = (a: Asset | 'new') => {
    reset(a === 'new'
      ? { hostname: '', ip: '', asset_type: 'server', os: '', owner_id: '', criticality: 2, environment: 'prod' }
      : { hostname: a.hostname, ip: a.ip ?? '', asset_type: a.asset_type, os: a.os ?? '', owner_id: a.owner_id ?? '', criticality: a.criticality, environment: a.environment })
    setEditing(a)
  }
  const save = useMutation({
    mutationFn: (v: Form) => {
      const body = { ...v, ip: v.ip || null, os: v.os || null, owner_id: v.owner_id || null }
      return editing === 'new' ? api.post('/assets', body) : api.patch(`/assets/${(editing as Asset).id}`, body)
    },
    onSuccess: () => { toast.success('Activo guardado'); setEditing(null); void refresh() },
    onError: (e: Error) => toast.error(e.message),
  })
  const toggle = useMutation({
    mutationFn: (a: Asset) => (a.is_active ? api.delete(`/assets/${a.id}`) : api.patch(`/assets/${a.id}`, { is_active: true })),
    onSuccess: () => { toast.success('Activo actualizado'); void refresh() },
    onError: (e: Error) => toast.error(e.message),
  })
  const exportAs = (fmt: 'csv' | 'xlsx') => download('/assets/export', { ...f, fmt }, `activos.${fmt}`).catch((e: Error) => toast.error(e.message))

  const total = list.data?.total ?? 0
  return (
    <>
      <PageHeader
        title="Activos"
        subtitle="Inventario sobre el que se cruzan KEV y EPSS. La criticidad de negocio pesa en el score de riesgo."
        actions={<>
          {can('assets', 'export') && <Button onClick={() => void exportAs('xlsx')}><DownloadSimple size={15} /> Excel</Button>}
          {can('assets', 'create') && <Button variant="primary" onClick={() => open('new')}><Plus size={15} weight="bold" /> Nuevo activo</Button>}
        </>}
      />
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Input aria-label="Buscar activos" placeholder="Hostname, IP o SO" value={f.q} onChange={set('q')} className="col-span-2 md:col-span-2" />
        <Select aria-label="Entorno" value={f.environment} onChange={set('environment')}>
          <option value="">Todos los entornos</option>
          {Object.entries(ENVIRONMENT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select aria-label="Criticidad" value={f.criticality} onChange={set('criticality')}>
          <option value="">Toda criticidad</option>
          {[4, 3, 2, 1].map((c) => <option key={c} value={c}>{CRITICALITY[c]}</option>)}
        </Select>
      </div>
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={7} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="No hay activos" hint="Registre un activo o importe hallazgos de un escáner para crearlos automáticamente."
            action={can('assets', 'create') ? <Button variant="primary" onClick={() => open('new')}>Nuevo activo</Button> : undefined} />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              <th className={th}>Hostname</th><th className={th}>IP</th><th className={th}>Tipo</th><th className={th}>Responsable</th>
              <th className={th}>Criticidad</th><th className={th}>Entorno</th><th className={th}><span className="sr-only">Acciones</span></th>
            </tr></thead>
            <tbody>
              {list.data.items.map((a) => (
                <tr key={a.id} className={a.is_active ? '' : 'opacity-60'}>
                  <td className={td}>
                    <span className="font-mono text-[12px] font-medium">{a.hostname}</span>
                    {a.auto_created && <span className="ml-2"><StatusBadge kind="warn">Por completar</StatusBadge></span>}
                    {!a.is_active && <span className="ml-2"><StatusBadge kind="neutral">Inactivo</StatusBadge></span>}
                    {a.os && <div className="text-[12px] text-muted">{a.os}</div>}
                  </td>
                  <td className={`${td} font-mono text-[12px]`}>{a.ip ?? '—'}</td>
                  <td className={td}>{ASSET_TYPE[a.asset_type]}</td>
                  <td className={td}>{a.owner_name ?? '—'}</td>
                  <td className={td}><StatusBadge kind={criticalityKind(a.criticality)}>{CRITICALITY[a.criticality]}</StatusBadge></td>
                  <td className={td}>{ENVIRONMENT[a.environment]}</td>
                  <td className={`${td} text-right whitespace-nowrap`}>
                    {can('assets', 'edit') && <Button variant="ghost" onClick={() => open(a)}>Editar</Button>}
                    {can('assets', 'delete') && <Button variant="ghost" onClick={() => toggle.mutate(a)}>{a.is_active ? 'Desactivar' : 'Reactivar'}</Button>}
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
      <Dialog open={editing !== null} onClose={() => setEditing(null)} title={editing === 'new' ? 'Nuevo activo' : 'Editar activo'}>
        <form className="space-y-3" noValidate onSubmit={handleSubmit((v) => save.mutate(v))}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Hostname" error={errors.hostname?.message}><Input {...register('hostname')} /></Field>
            <Field label="IP" error={errors.ip?.message}><Input placeholder="10.0.0.1" {...register('ip')} /></Field>
            <Field label="Tipo"><Select {...register('asset_type')}>{Object.entries(ASSET_TYPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
            <Field label="Sistema operativo"><Input {...register('os')} /></Field>
            <Field label="Criticidad de negocio"><Select {...register('criticality')}>{[4, 3, 2, 1].map((c) => <option key={c} value={c}>{CRITICALITY[c]}</option>)}</Select></Field>
            <Field label="Entorno"><Select {...register('environment')}>{Object.entries(ENVIRONMENT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
          </div>
          {users.data && (
            <Field label="Responsable">
              <Select {...register('owner_id')}><option value="">Sin asignar</option>{users.data.items.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select>
            </Field>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" onClick={() => setEditing(null)}>Cancelar</Button>
            <Button type="submit" variant="primary" disabled={save.isPending}>Guardar</Button>
          </div>
        </form>
      </Dialog>
    </>
  )
}
