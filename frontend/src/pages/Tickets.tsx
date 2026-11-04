import { Kanban, Table } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { SlaBar, TicketDrawer } from '../components/detail'
import { DataTable, Meta, Pagination, rowOpen, stop, type Column } from '../components/kit'
import { Button, EmptyState, ErrorState, Input, PageHeader, Select, Skeleton, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { useAuth, type User } from '../lib/auth'
import { PRIORITY, TICKET_STATUS } from '../lib/labels'
import type { TicketRow } from '../lib/types'

export type { TicketRow }

const PAGE = 50
type View = 'table' | 'board'

// Columnas del tablero: estados agrupados como los entiende quien remedia.
const BOARD: Array<{ title: string; statuses: string[] }> = [
  { title: 'Abiertos', statuses: ['open'] },
  { title: 'En remediación', statuses: ['in_progress'] },
  { title: 'Resueltos', statuses: ['resolved', 'closed'] },
  { title: 'Riesgo aceptado', statuses: ['risk_accepted'] },
]

function Card({ t, onOpen }: { t: TicketRow; onOpen: () => void }) {
  return (
    <button type="button" onClick={onOpen} className="block w-full rounded-lg border border-line bg-surface p-3 text-left transition-colors duration-150 hover:border-line-strong">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[12px] font-medium">{t.code}</span>
        <StatusBadge kind={PRIORITY[t.priority][0]}>{PRIORITY[t.priority][1]}</StatusBadge>
      </div>
      <p className="mt-1 text-[13px]"><span className="font-mono text-[12px] font-medium">{t.cve_id}</span> <span className="text-muted">en</span> <span className="font-mono text-[12px]">{t.hostname}</span></p>
      <p className="mt-1 text-[12px] text-muted">{t.assignee?.name ?? 'Sin asignar'}</p>
      <div className="mt-2"><SlaBar created={t.created_at} due={t.due_date} state={t.sla_state} /></div>
    </button>
  )
}

export default function Tickets() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { can } = useAuth()
  const [search] = useSearchParams()
  const [view, setView] = useState<View>('table')
  const [f, setF] = useState({ q: '', status: search.get('status') ?? 'active', priority: '', mine: false, overdue: search.get('overdue') === '1' })
  const [page, setPage] = useState(0)
  const [sel, setSel] = useState<TicketRow | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [assignee, setAssignee] = useState('')

  const board = view === 'board'
  const params = { ...f, status: board ? '' : f.status, mine: f.mine || undefined, overdue: f.overdue || undefined, limit: board ? 200 : PAGE, offset: board ? 0 : page * PAGE }
  const list = useQuery({ queryKey: ['tickets', params], queryFn: () => api.get<{ items: TicketRow[]; total: number }>('/tickets', params) })
  // "Sin asignar" se cuenta sobre todos los tickets activos (la API no filtra por sin asignar).
  const active = useQuery({ queryKey: ['tickets', 'active-all'], queryFn: () => api.get<{ items: TicketRow[]; total: number }>('/tickets', { status: 'active', limit: 200 }) })
  const unassigned = active.data?.items.filter((t) => !t.assignee).length ?? null

  const canBulk = can('tickets', 'edit') && can('users', 'view')
  const users = useQuery({ queryKey: ['users', '', 0, 'all'], queryFn: () => api.get<{ items: User[] }>('/users', { limit: 200 }), enabled: canBulk })
  const assign = useMutation({
    mutationFn: (ids: string[]) => Promise.all(ids.map((id) => api.patch(`/tickets/${id}`, { assignee_id: assignee || null }))),
    onSuccess: (_, ids) => {
      toast.success(`${ids.length} ${ids.length === 1 ? 'ticket asignado' : 'tickets asignados'}`)
      setPicked(new Set())
      void qc.invalidateQueries({ queryKey: ['tickets'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const set = (k: 'q' | 'status' | 'priority') => (e: { target: { value: string } }) => { setF({ ...f, [k]: e.target.value }); setPage(0); setPicked(new Set()) }
  const flag = (k: 'mine' | 'overdue') => (e: { target: { checked: boolean } }) => { setF({ ...f, [k]: e.target.checked }); setPage(0); setPicked(new Set()) }
  const total = list.data?.total ?? 0
  const rows = list.data?.items
  const allPicked = !!rows?.length && rows.every((t) => picked.has(t.id))
  const toggle = (id: string) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const toggleAll = () => setPicked(allPicked ? new Set() : new Set(rows?.map((t) => t.id)))

  const columns: Column<TicketRow>[] = useMemo(() => {
    const cols: Column<TicketRow>[] = [
      {
        key: 'code', header: 'Código', className: 'font-mono text-[12px] font-medium whitespace-nowrap',
        cell: (t) => <a href={`/tickets/${t.id}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); nav(`/tickets/${t.id}`) }} className="hover:underline">{t.code}</a>,
      },
      { key: 'finding', header: 'Hallazgo', cell: (t) => <><span className="font-mono text-[12px] font-medium whitespace-nowrap">{t.cve_id}</span> <span className="text-muted">en</span> <span className="font-mono text-[12px] whitespace-nowrap">{t.hostname}</span></> },
      { key: 'prio', header: 'Prioridad', cell: (t) => <StatusBadge kind={PRIORITY[t.priority][0]}>{PRIORITY[t.priority][1]}</StatusBadge> },
      { key: 'status', header: 'Estado', cell: (t) => <Meta>{TICKET_STATUS[t.status][1]}</Meta> },
      { key: 'owner', header: 'Responsable', cell: (t) => t.assignee?.name ?? <span className="text-muted">Sin asignar</span> },
      { key: 'sla', header: 'SLA', cell: (t) => <SlaBar created={t.created_at} due={t.due_date} state={t.sla_state} /> },
    ]
    if (!canBulk) return cols
    return [
      {
        key: 'pick', header: <input type="checkbox" aria-label="Seleccionar todos los tickets de esta página" className="accent-[var(--accent)]" checked={allPicked} onChange={toggleAll} />,
        cell: (t) => <span onClick={stop} onKeyDown={stop}><input type="checkbox" aria-label={`Seleccionar ${t.code}`} className="accent-[var(--accent)]" checked={picked.has(t.id)} onChange={() => toggle(t.id)} /></span>,
      },
      ...cols,
    ]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canBulk, picked, allPicked, rows])

  return (
    <>
      <PageHeader
        title="Tickets de remediación"
        subtitle="Un ticket por cada hallazgo KEV nuevo, con responsable y SLA. Resolverlo mitiga el hallazgo."
        actions={
          <>
            {unassigned !== null && <span className="text-[13px] text-muted" aria-live="polite">Sin asignar: <span className="font-medium text-ink tabular-nums">{unassigned}</span></span>}
            <div role="group" aria-label="Vista" className="flex gap-1">
              {([['table', 'Tabla', Table], ['board', 'Tablero', Kanban]] as const).map(([v, label, Icon]) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={view === v}
                  onClick={() => { setView(v); setPicked(new Set()) }}
                  className={`inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors duration-150 pointer-coarse:h-11 ${view === v ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}
                >
                  <Icon size={15} aria-hidden /> {label}
                </button>
              ))}
            </div>
          </>
        }
      />
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-6">
        <Input aria-label="Buscar tickets" placeholder="Código, CVE u hostname" value={f.q} onChange={set('q')} className="col-span-2" />
        <Select aria-label="Estado" value={f.status} onChange={set('status')} disabled={board} title={board ? 'El tablero muestra todos los estados' : undefined}>
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

      {canBulk && picked.size > 0 && !board && (
        <div role="region" aria-label="Asignación masiva" className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-sunken px-3 py-2 text-[13px]">
          <span className="font-medium">{picked.size} {picked.size === 1 ? 'seleccionado' : 'seleccionados'}</span>
          <Select aria-label="Asignar a" className="!w-auto min-w-[180px]" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">Sin asignar</option>
            {users.data?.items.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </Select>
          <Button variant="primary" disabled={assign.isPending} onClick={() => assign.mutate([...picked])}>Asignar</Button>
          <Button variant="ghost" onClick={() => setPicked(new Set())}>Limpiar selección</Button>
        </div>
      )}

      {board ? (
        list.isPending ? <Skeleton cols={4} rows={6} /> : list.isError ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} /> : rows && rows.length === 0 ? (
          <EmptyState title="No hay tickets" hint="Ningún ticket coincide con los filtros." />
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {BOARD.map((col) => {
              const items = rows?.filter((t) => col.statuses.includes(t.status)) ?? []
              return (
                <section key={col.title} aria-label={col.title} className="rounded-lg bg-sunken p-2">
                  <h2 className="flex items-center justify-between px-1 pb-2 text-[13px] font-semibold">{col.title}<span className="font-normal tabular-nums text-muted">{items.length}</span></h2>
                  <div className="space-y-2">
                    {items.length === 0 ? <p className="px-1 py-3 text-[12px] text-muted">Sin tickets</p> : items.map((t) => <Card key={t.id} t={t} onOpen={() => setSel(t)} />)}
                  </div>
                </section>
              )
            })}
          </div>
        )
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(t) => t.id}
            loading={list.isPending}
            error={list.isError ? list.error.message : undefined}
            onRetry={() => void list.refetch()}
            rowProps={(t) => rowOpen(() => setSel(t))}
            empty={<EmptyState title="No hay tickets" hint={f.q || f.priority || f.mine || f.overdue || f.status !== 'active' ? 'Ningún ticket coincide con los filtros.' : 'Se crean automáticamente cuando el cruce diario encuentra una vulnerabilidad KEV nueva en su entorno.'} />}
          />
          <Pagination page={page} total={total} pageSize={PAGE} onPage={(p) => { setPage(p); setPicked(new Set()) }} />
        </>
      )}
      <TicketDrawer t={sel} onClose={() => setSel(null)} />
    </>
  )
}
