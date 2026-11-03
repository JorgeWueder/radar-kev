import { DownloadSimple, ShieldCheck } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  Button, EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton, StatusBadge, td, th,
} from '../components/ui'
import { api, download } from '../lib/api'
import { useAuth, type User } from '../lib/auth'
import { formatDuration, formatLima, limaInputToIso } from '../lib/format'
import { moduleLabel } from '../lib/permissions'

interface Entry {
  id: number; ts: string; user_email: string | null; actor: string; module: string; action: string
  result: 'success' | 'failure' | 'denied'; ip: string | null; duration_ms: number | null
  detail: Record<string, unknown>
}
interface Page { items: Entry[]; total: number }
interface Verify { ok: boolean; checked: number; first_broken_id: number | null }
interface Catalog { modules: string[] }

const PAGE = 50
const RESULT = { success: ['ok', 'Éxito'], failure: ['danger', 'Fallo'], denied: ['warn', 'Denegado'] } as const

export default function Audit() {
  const { can } = useAuth()
  const [f, setF] = useState({ user_id: '', module: '', action: '', result: '', from: '', to: '' })
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<number | null>(null)
  const [verify, setVerify] = useState<Verify | null>(null)

  const params = {
    user_id: f.user_id, module: f.module, action: f.action, result: f.result,
    date_from: limaInputToIso(f.from), date_to: limaInputToIso(f.to),
  }
  const list = useQuery({
    queryKey: ['audit', params, page],
    queryFn: () => api.get<Page>('/audit', { ...params, limit: PAGE, offset: page * PAGE }),
  })
  const modules = useQuery({ queryKey: ['permissions'], queryFn: () => api.get<Catalog>('/permissions'), enabled: can('roles', 'view') })
  const users = useQuery({ queryKey: ['users', '', 0, 'all'], queryFn: () => api.get<{ items: User[] }>('/users', { limit: 200 }), enabled: can('users', 'view') })

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => { setF({ ...f, [k]: e.target.value }); setPage(0) }
  const total = list.data?.total ?? 0

  const exportAs = (fmt: 'csv' | 'xlsx') =>
    download('/audit/export', { ...params, fmt }, `bitacora.${fmt}`).catch((e: Error) => toast.error(e.message))
  const runVerify = async () => {
    try { setVerify(await api.get<Verify>('/audit/verify')) } catch (e) { toast.error((e as Error).message) }
  }

  return (
    <>
      <PageHeader
        title="Bitácora de auditoría"
        subtitle="Registro solo de añadir, encadenado por hash. Las horas se muestran en America/Lima; se guardan en UTC."
        actions={<>
          <Button onClick={() => void runVerify()}><ShieldCheck size={15} /> Verificar integridad</Button>
          {can('audit', 'export') && <>
            <Button onClick={() => void exportAs('csv')}><DownloadSimple size={15} /> CSV</Button>
            <Button onClick={() => void exportAs('xlsx')}><DownloadSimple size={15} /> Excel</Button>
          </>}
        </>}
      />
      {verify && (
        <div className="mb-3" role="status">
          {verify.ok
            ? <StatusBadge kind="ok">Cadena íntegra: {verify.checked} registros verificados</StatusBadge>
            : <StatusBadge kind="danger">Cadena alterada: primer eslabón roto en el registro {verify.first_broken_id}</StatusBadge>}
        </div>
      )}
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Select aria-label="Usuario" value={f.user_id} onChange={set('user_id')} disabled={!users.data}>
          <option value="">Todos los usuarios</option>
          {users.data?.items.map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
        </Select>
        <Select aria-label="Módulo" value={f.module} onChange={set('module')}>
          <option value="">Todos los módulos</option>
          {(modules.data?.modules ?? []).concat(['auth', 'app']).map((m) => <option key={m} value={m}>{moduleLabel(m)}</option>)}
        </Select>
        <Input aria-label="Acción" placeholder="Acción (p. ej. login)" value={f.action} onChange={set('action')} />
        <Select aria-label="Resultado" value={f.result} onChange={set('result')}>
          <option value="">Todos los resultados</option>
          <option value="success">Éxito</option><option value="failure">Fallo</option><option value="denied">Denegado</option>
        </Select>
        <Input aria-label="Desde (hora de Lima)" type="datetime-local" value={f.from} onChange={set('from')} />
        <Input aria-label="Hasta (hora de Lima)" type="datetime-local" value={f.to} onChange={set('to')} />
      </div>
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={7} rows={8} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="Sin registros" hint="Ningún evento coincide con los filtros aplicados." />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              <th className={th}>Fecha (Lima)</th><th className={th}>Usuario</th><th className={th}>Módulo</th>
              <th className={th}>Acción</th><th className={th}>Resultado</th><th className={th}>IP</th>
              <th className={`${th} text-right`}>Duración</th>
            </tr></thead>
            <tbody>
              {list.data.items.map((e) => {
                const [kind, label] = RESULT[e.result]
                const hasDetail = Object.keys(e.detail).length > 0
                return (
                  <>
                    <tr key={e.id} className={hasDetail ? 'cursor-pointer hover:bg-sunken' : ''} onClick={() => hasDetail && setOpen(open === e.id ? null : e.id)}>
                      <td className={`${td} font-mono text-[12px] whitespace-nowrap`}>{formatLima(e.ts)}</td>
                      <td className={td}>{e.user_email ?? (e.actor === 'user' ? '—' : e.actor)}</td>
                      <td className={td}>{moduleLabel(e.module)}</td>
                      <td className={`${td} font-mono text-[12px]`}>{e.action}</td>
                      <td className={td}><StatusBadge kind={kind}>{label}</StatusBadge></td>
                      <td className={`${td} font-mono text-[12px]`}>{e.ip ?? '—'}</td>
                      <td className={`${td} text-right tabular-nums`}>{formatDuration(e.duration_ms)}</td>
                    </tr>
                    {open === e.id && (
                      <tr key={`${e.id}-d`}><td colSpan={7} className="border-b border-line bg-sunken px-3 py-2">
                        <pre className="overflow-x-auto font-mono text-[12px]">{JSON.stringify(e.detail, null, 2)}</pre>
                      </td></tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        )}
      </Panel>
      {total > 0 && (
        <div className="mt-3 flex items-center justify-between text-[13px] text-muted">
          <span>{page * PAGE + 1}–{Math.min((page + 1) * PAGE, total)} de {total}</span>
          <div className="flex gap-2">
            <Button disabled={page === 0} onClick={() => setPage(page - 1)}>Anterior</Button>
            <Button disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Siguiente</Button>
          </div>
        </div>
      )}
    </>
  )
}
