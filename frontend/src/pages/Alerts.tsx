import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Button, EmptyState, ErrorState, PageHeader, Panel, Skeleton, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { formatLima } from '../lib/format'
import { BAND, type Kind } from '../lib/labels'

interface Alert {
  id: string; alert_type: string; severity: string; message: string; created_at: string; is_read: boolean
  cve_id: string | null; hostname: string | null; ticket_id: string | null
  deliveries: { channel: string; status: string; last_error: string | null }[]
}
interface AlertList { items: Alert[]; total: number; unread: number }

const PAGE = 30
const CHANNEL: Record<string, string> = { email: 'Correo', webhook: 'Webhook' }
const DELIVERY: Record<string, [Kind, string]> = { sent: ['ok', 'enviado'], failed: ['danger', 'falló'], skipped: ['neutral', 'sin configurar'], pending: ['neutral', 'pendiente'] }

export default function Alerts() {
  const qc = useQueryClient()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [page, setPage] = useState(0)
  const list = useQuery({
    queryKey: ['alerts', unreadOnly, page],
    queryFn: () => api.get<AlertList>('/alerts', { unread_only: unreadOnly || undefined, limit: PAGE, offset: page * PAGE }),
    refetchInterval: 30_000,
  })
  const refresh = () => { void qc.invalidateQueries({ queryKey: ['alerts'] }); void qc.invalidateQueries({ queryKey: ['alerts-unread'] }) }
  const read = useMutation({ mutationFn: (id: string) => api.post(`/alerts/${id}/read`), onSuccess: refresh })
  const readAll = useMutation({
    mutationFn: () => api.post('/alerts/read-all'),
    onSuccess: () => { toast.success('Todas las alertas marcadas como leídas'); refresh() },
    onError: (e: Error) => toast.error(e.message),
  })
  const total = list.data?.total ?? 0

  return (
    <>
      <PageHeader
        title="Alertas"
        subtitle={list.data ? `${list.data.unread} sin leer` : 'Nuevas vulnerabilidades KEV en su entorno y avisos del flujo diario'}
        actions={<>
          <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" className="accent-[var(--accent)]" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); setPage(0) }} /> Solo sin leer</label>
          <Button disabled={!list.data?.unread || readAll.isPending} onClick={() => readAll.mutate()}>Marcar todas como leídas</Button>
        </>}
      />
      <Panel>
        {list.isPending ? <Skeleton cols={3} rows={6} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title={unreadOnly ? 'No hay alertas sin leer' : 'Sin alertas'} hint="Aparecen cuando el cruce diario encuentra una vulnerabilidad KEV nueva en su inventario." />
        ) : (
          <ul className="divide-y divide-line">
            {list.data.items.map((a) => {
              const isSource = a.alert_type === 'source_unavailable'
              const [kind, label] = isSource ? (['warn', 'Fuente no disponible'] as [Kind, string]) : BAND[a.severity] ?? (['neutral', a.severity] as [Kind, string])
              return (
                <li key={a.id} className={`flex flex-wrap items-start gap-3 px-4 py-3 ${a.is_read ? '' : 'bg-sunken'}`}>
                  <div className="min-w-0 flex-1">
                    <div className="mb-0.5 flex flex-wrap items-center gap-2">
                      <StatusBadge kind={kind}>{label}</StatusBadge>
                      {!a.is_read && <span className="text-[12px] font-medium">Nueva</span>}
                      <span className="font-mono text-[12px] text-muted">{formatLima(a.created_at)}</span>
                    </div>
                    <p className="break-words text-[13px]">{a.message}</p>
                    <p className="mt-1 flex flex-wrap gap-x-3 text-[12px] text-muted">
                      {a.deliveries.map((d) => (
                        <span key={d.channel} title={d.last_error ?? undefined}>{CHANNEL[d.channel] ?? d.channel}: {DELIVERY[d.status]?.[1] ?? d.status}</span>
                      ))}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    {a.ticket_id && <Link to={`/tickets/${a.ticket_id}`} className="rounded-md px-2 py-1 text-[13px] font-medium text-link hover:bg-sunken" onClick={() => !a.is_read && read.mutate(a.id)}>Ver ticket</Link>}
                    {!a.is_read && <Button variant="ghost" onClick={() => read.mutate(a.id)}>Marcar leída</Button>}
                  </div>
                </li>
              )
            })}
          </ul>
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
