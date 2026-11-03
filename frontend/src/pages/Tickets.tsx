import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button, EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api } from '../lib/api'
import { formatDate } from '../lib/format'
import { PRIORITY, SLA, TICKET_STATUS } from '../lib/labels'

export interface TicketRow {
  id: string; code: string; title: string; status: string; priority: string; assignee: { id: string; name: string } | null
  due_date: string | null; sla_state: string; cve_id: string; hostname: string; created_at: string; ai_generated: boolean
}

const PAGE = 50

export default function Tickets() {
  const nav = useNavigate()
  const [f, setF] = useState({ q: '', status: 'active', priority: '', mine: false, overdue: false })
  const [page, setPage] = useState(0)
  const params = { ...f, mine: f.mine || undefined, overdue: f.overdue || undefined, limit: PAGE, offset: page * PAGE }
  const list = useQuery({ queryKey: ['tickets', params], queryFn: () => api.get<{ items: TicketRow[]; total: number }>('/tickets', params) })
  const set = (k: 'q' | 'status' | 'priority') => (e: { target: { value: string } }) => { setF({ ...f, [k]: e.target.value }); setPage(0) }
  const flag = (k: 'mine' | 'overdue') => (e: { target: { checked: boolean } }) => { setF({ ...f, [k]: e.target.checked }); setPage(0) }
  const total = list.data?.total ?? 0

  return (
    <>
      <PageHeader title="Tickets de remediación" subtitle="Un ticket por cada hallazgo KEV nuevo, con responsable y SLA. Resolverlo mitiga el hallazgo." />
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-6">
        <Input aria-label="Buscar tickets" placeholder="Código, CVE u hostname" value={f.q} onChange={set('q')} className="col-span-2" />
        <Select aria-label="Estado" value={f.status} onChange={set('status')}>
          <option value="active">Activos</option><option value="">Todos</option>
          {Object.entries(TICKET_STATUS).map(([k, [, l]]) => <option key={k} value={k}>{l}</option>)}
        </Select>
        <Select aria-label="Prioridad" value={f.priority} onChange={set('priority')}>
          <option value="">Toda prioridad</option>
          {Object.entries(PRIORITY).map(([k, [, l]]) => <option key={k} value={k}>{l}</option>)}
        </Select>
        <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" className="accent-[var(--accent)]" checked={f.mine} onChange={flag('mine')} /> Asignados a mí</label>
        <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" className="accent-[var(--accent)]" checked={f.overdue} onChange={flag('overdue')} /> SLA vencido</label>
      </div>
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={6} rows={8} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="No hay tickets" hint={f.q || f.priority || f.mine || f.overdue || f.status !== 'active' ? 'Ningún ticket coincide con los filtros.' : 'Se crean automáticamente cuando el cruce diario encuentra una vulnerabilidad KEV nueva en su entorno.'} />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              <th className={th}>Código</th><th className={th}>Hallazgo</th><th className={th}>Prioridad</th><th className={th}>Estado</th>
              <th className={th}>Responsable</th><th className={th}>SLA</th>
            </tr></thead>
            <tbody>
              {list.data.items.map((t) => {
                const [pk, pl] = PRIORITY[t.priority]
                const [sk, sl] = TICKET_STATUS[t.status]
                const [lk, ll] = SLA[t.sla_state]
                return (
                  <tr key={t.id} className="cursor-pointer hover:bg-sunken" onClick={() => nav(`/tickets/${t.id}`)}>
                    <td className={`${td} font-mono text-[12px] font-medium whitespace-nowrap`}>
                      <a href={`/tickets/${t.id}`} onClick={(e) => { e.preventDefault(); nav(`/tickets/${t.id}`) }} className="hover:underline">{t.code}</a>
                    </td>
                    <td className={td}><span className="font-mono text-[12px] font-medium whitespace-nowrap">{t.cve_id}</span> <span className="text-muted">en</span> <span className="font-mono text-[12px] whitespace-nowrap">{t.hostname}</span></td>
                    <td className={td}><StatusBadge kind={pk}>{pl}</StatusBadge></td>
                    <td className={td}><StatusBadge kind={sk}>{sl}</StatusBadge></td>
                    <td className={td}>{t.assignee?.name ?? <span className="text-muted">Sin asignar</span>}</td>
                    <td className={`${td} whitespace-nowrap`}><StatusBadge kind={lk}>{ll}</StatusBadge>{t.due_date && t.sla_state !== 'no_aplica' && <div className="mt-0.5 text-[12px] tabular-nums text-muted">{formatDate(t.due_date)}</div>}</td>
                  </tr>
                )
              })}
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
    </>
  )
}
