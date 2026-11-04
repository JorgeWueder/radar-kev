import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'

import { toast } from 'sonner'

import { Button, rowToggle, EmptyState, ErrorState, PageHeader, Panel, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDuration, formatLima } from '../lib/format'
import type { Kind } from '../lib/labels'

interface Run {
  id: string; run_date: string; trigger: string; status: string; kev_catalog_version: string | null
  kev_total: number; epss_scored: number; new_matches: number; alerts_created: number
  errors: { node: string; message: string; at: string }[]; started_at: string; finished_at: string | null
}

const STATUS: Record<string, [Kind, string]> = {
  success: ['ok', 'Correcta'], partial: ['warn', 'Con avisos'], failed: ['danger', 'Fallida'], running: ['neutral', 'En curso'],
}

export default function Runs() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [open, setOpen] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['runs'], queryFn: () => api.get<{ items: Run[]; total: number }>('/workflow-runs'), refetchInterval: 30_000 })

  const trigger = useMutation({
    mutationFn: () => api.post('/workflow-runs/trigger'),
    onSuccess: () => {
      toast.success('Flujo iniciado en n8n; el resultado aparecerá aquí en unos segundos')
      for (const ms of [4000, 12000, 30000]) setTimeout(() => void qc.invalidateQueries({ queryKey: ['runs'] }), ms)
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <>
      <PageHeader
        title="Ejecuciones del workflow"
        subtitle="Cruce diario de KEV y EPSS con el inventario, orquestado por n8n. Un fallo de una fuente externa aparece aquí en rojo."
        actions={can('workflow', 'create') && <Button variant="primary" disabled={trigger.isPending} onClick={() => trigger.mutate()}>{trigger.isPending ? 'Iniciando…' : 'Ejecutar ahora'}</Button>}
      />
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={7} rows={5} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="Aún no hay ejecuciones" hint="La primera corre a las 06:00 (hora de Lima) cuando el workflow de n8n esté importado y activo." />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              <th className={th}>Inicio (Lima)</th><th className={th}>Disparo</th><th className={th}>Estado</th><th className={th}>Catálogo KEV</th>
              <th className={`${th} text-right`}>EPSS</th><th className={`${th} text-right`}>Nuevas en KEV</th><th className={`${th} text-right`}>Alertas</th><th className={`${th} text-right`}>Duración</th>
            </tr></thead>
            <tbody>
              {list.data.items.map((r) => {
                const [kind, label] = STATUS[r.status] ?? ['neutral', r.status]
                const ms = r.finished_at ? new Date(r.finished_at).getTime() - new Date(r.started_at).getTime() : null
                return (
                  <Fragment key={r.id}>
                    <tr {...(r.errors.length ? rowToggle(open === r.id, () => setOpen(open === r.id ? null : r.id)) : {})}>
                      <td className={`${td} font-mono text-[12px] whitespace-nowrap`}>{formatLima(r.started_at)}</td>
                      <td className={td}>{r.trigger === 'cron' ? 'Programado' : 'Manual'}</td>
                      <td className={td}><StatusBadge kind={kind}>{label}</StatusBadge></td>
                      <td className={`${td} font-mono text-[12px]`}>{r.kev_catalog_version ?? '—'}{r.kev_total > 0 && <span className="text-muted"> · {r.kev_total}</span>}</td>
                      <td className={`${td} text-right tabular-nums`}>{r.epss_scored}</td>
                      <td className={`${td} text-right tabular-nums`}>{r.new_matches}</td>
                      <td className={`${td} text-right tabular-nums`}>{r.alerts_created}</td>
                      <td className={`${td} text-right tabular-nums`}>{formatDuration(ms)}</td>
                    </tr>
                    {open === r.id && (
                      <tr><td colSpan={8} className="border-b border-line bg-sunken px-4 py-3">
                        <ul className="space-y-1 text-[12px]">
                          {r.errors.map((e, i) => <li key={i}><span className="font-mono font-medium">{e.node}</span>: {e.message} <span className="text-muted">({formatLima(e.at)})</span></li>)}
                        </ul>
                      </td></tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  )
}
