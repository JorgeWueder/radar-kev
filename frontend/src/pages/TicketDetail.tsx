import { ArrowLeft, Sparkle } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { Button, ErrorState, Field, Panel, Select, Skeleton, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { useAuth, type User } from '../lib/auth'
import { formatDate, formatLima } from '../lib/format'
import { PRIORITY, SLA, TICKET_STATUS } from '../lib/labels'
import type { TicketRow } from './Tickets'

interface Event { id: number; event: string; user: string | null; data: Record<string, unknown>; at: string }
interface Detail extends TicketRow {
  description: string; ai_enrichment: Record<string, unknown> | null; vulnerability_id: string
  cvss_score: number | null; risk_score: number | null; asset_criticality: number; resolved_at: string | null; events: Event[]
}

function eventText(e: Event): string {
  const d = e.data
  const st = (v: unknown) => TICKET_STATUS[String(v)]?.[1] ?? String(v)
  switch (e.event) {
    case 'created': return 'Ticket creado por el flujo diario'
    case 'status': return `Estado: ${st(d.from)} → ${st(d.to)}`
    case 'priority': return `Prioridad: ${PRIORITY[String(d.from)]?.[1]} → ${PRIORITY[String(d.to)]?.[1]}`
    case 'assignee': return d.to ? `Asignado a ${String(d.to)}` : 'Asignación retirada'
    case 'comment': return String(d.text ?? '')
    case 'enriched': return 'Descripción enriquecida con IA'
    default: return e.event
  }
}

export default function TicketDetail() {
  const { id } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const [comment, setComment] = useState('')
  const t = useQuery({ queryKey: ['ticket', id], queryFn: () => api.get<Detail>(`/tickets/${id}`) })
  const users = useQuery({ queryKey: ['users', '', 0, 'all'], queryFn: () => api.get<{ items: User[] }>('/users', { limit: 200 }), enabled: can('users', 'view') })

  const refresh = () => { void qc.invalidateQueries({ queryKey: ['ticket', id] }); void qc.invalidateQueries({ queryKey: ['tickets'] }); void qc.invalidateQueries({ queryKey: ['vulnerabilities'] }) }
  const patch = useMutation({
    mutationFn: (body: object) => api.patch(`/tickets/${id}`, body),
    onSuccess: () => { toast.success('Ticket actualizado'); refresh() },
    onError: (e: Error) => toast.error(e.message),
  })
  const post = useMutation({
    mutationFn: () => api.post(`/tickets/${id}/comments`, { text: comment }),
    onSuccess: () => { setComment(''); refresh() },
    onError: (e: Error) => toast.error(e.message),
  })

  if (t.isPending) return <Panel><Skeleton cols={3} rows={8} /></Panel>
  if (t.isError) return <Panel><ErrorState message={t.error.message} onRetry={() => void t.refetch()} /></Panel>
  const d = t.data
  const editable = can('tickets', 'edit')
  const [pk, pl] = PRIORITY[d.priority]
  const [lk, ll] = SLA[d.sla_state]
  const ai = d.ai_enrichment as { resumen?: string; por_que_urgente?: string[]; pasos_remediacion?: string[]; fuentes?: string[] } | null

  return (
    <>
      <Link to="/tickets" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink"><ArrowLeft size={14} /> Tickets</Link>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[12px] text-muted">{d.code}</p>
          <h1 className="break-words text-[20px] font-semibold leading-tight">{d.title}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
            <StatusBadge kind={pk}>Prioridad {pl.toLowerCase()}</StatusBadge>
            <StatusBadge kind={lk}>SLA {ll.toLowerCase()}{d.due_date ? ` · ${formatDate(d.due_date)}` : ''}</StatusBadge>
            <span>Creado {formatLima(d.created_at)}</span>
          </p>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Panel className="p-4">
            <h2 className="mb-2 text-[14px] font-semibold">Descripción</h2>
            <p className="whitespace-pre-line break-words text-[13px]">{d.description}</p>
          </Panel>
          {ai && (
            <Panel className="p-4">
              <h2 className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold">
                Análisis <span className="inline-flex items-center gap-1 rounded bg-sunken px-1.5 py-0.5 text-[11px] font-medium text-muted"><Sparkle size={12} weight="fill" aria-hidden /> Generado por IA</span>
              </h2>
              {ai.resumen && <p className="mb-2 text-[13px]">{ai.resumen}</p>}
              {ai.por_que_urgente && <ul className="mb-2 list-disc pl-5 text-[13px]">{ai.por_que_urgente.map((x) => <li key={x}>{x}</li>)}</ul>}
              {ai.pasos_remediacion && <><p className="text-[12px] font-medium text-muted">Pasos de remediación</p><ol className="list-decimal pl-5 text-[13px]">{ai.pasos_remediacion.map((x) => <li key={x}>{x}</li>)}</ol></>}
            </Panel>
          )}
          <Panel className="p-4">
            <h2 className="mb-3 text-[14px] font-semibold">Historial</h2>
            {editable && (
              <form className="mb-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (comment.trim()) post.mutate() }}>
                <input aria-label="Comentario" placeholder="Agregar un comentario…" maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} className="h-8 flex-1 rounded-md border border-line bg-surface px-2.5 text-[13px]" />
                <Button type="submit" variant="primary" disabled={!comment.trim() || post.isPending}>Comentar</Button>
              </form>
            )}
            <ol className="space-y-2.5">
              {d.events.map((e) => (
                <li key={e.id} className="text-[13px]">
                  <p className={e.event === 'comment' ? '' : 'text-muted'}>{eventText(e)}</p>
                  <p className="text-[12px] text-muted">{e.user ?? 'Sistema'} · <span className="font-mono">{formatLima(e.at)}</span></p>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
        <Panel className="h-fit space-y-3 p-4">
          <Field label="Estado">
            <Select value={d.status} disabled={!editable || patch.isPending} onChange={(e) => patch.mutate({ status: e.target.value })}>
              {Object.entries(TICKET_STATUS).map(([k, [, l]]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Prioridad">
            <Select value={d.priority} disabled={!editable || patch.isPending} onChange={(e) => patch.mutate({ priority: e.target.value })}>
              {Object.entries(PRIORITY).map(([k, [, l]]) => <option key={k} value={k}>{l}</option>)}
            </Select>
          </Field>
          <Field label="Responsable">
            {users.data ? (
              <Select value={d.assignee?.id ?? ''} disabled={!editable || patch.isPending} onChange={(e) => patch.mutate({ assignee_id: e.target.value || null })}>
                <option value="">Sin asignar</option>
                {users.data.items.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
              </Select>
            ) : <p className="text-[13px]">{d.assignee?.name ?? 'Sin asignar'}</p>}
          </Field>
          <dl className="grid grid-cols-[100px_1fr] gap-y-1.5 border-t border-line pt-3 text-[13px]">
            <dt className="text-muted">Hallazgo</dt><dd className="font-mono text-[12px]">{d.cve_id}</dd>
            <dt className="text-muted">Activo</dt><dd className="font-mono text-[12px]">{d.hostname}</dd>
            <dt className="text-muted">CVSS</dt><dd className="tabular-nums">{d.cvss_score ?? '—'}</dd>
            <dt className="text-muted">Riesgo</dt><dd className="tabular-nums">{d.risk_score?.toFixed(1) ?? '—'}</dd>
            <dt className="text-muted">Resuelto</dt><dd>{d.resolved_at ? formatLima(d.resolved_at) : '—'}</dd>
          </dl>
        </Panel>
      </div>
    </>
  )
}
