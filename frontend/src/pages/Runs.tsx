import { CaretDown, CaretRight } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { DataTable, Meta, rowOpen, type Column } from '../components/kit'
import { Button, EmptyState, PageHeader, Panel, StatusBadge } from '../components/ui'
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

const durationMs = (r: Run) => (r.finished_at ? new Date(r.finished_at).getTime() - new Date(r.started_at).getTime() : null)

/** Mini-gráfica de la duración de las últimas ejecuciones (de la más antigua a la más reciente). Las fallidas, en rojo. */
function DurationChart({ runs }: { runs: Run[] }) {
  const pts = runs.filter((r) => durationMs(r) !== null).slice(0, 20).reverse()
  if (pts.length < 2) return null
  const max = Math.max(...pts.map((r) => durationMs(r) ?? 0), 1)
  const W = 10
  const H = 44
  const last = pts[pts.length - 1]
  return (
    <Panel className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
      <div>
        <h2 className="text-[14px] font-semibold">Duración de las últimas {pts.length} ejecuciones</h2>
        <p className="text-[12px] text-muted">
          Última: <span className="tabular-nums text-ink">{formatDuration(durationMs(last))}</span> · máxima: <span className="tabular-nums text-ink">{formatDuration(max)}</span>
        </p>
      </div>
      <svg viewBox={`0 0 ${pts.length * W} ${H}`} className="h-11 min-w-[160px] flex-1 text-muted" preserveAspectRatio="none" role="img" aria-label={`Duración de las últimas ${pts.length} ejecuciones; la última tardó ${formatDuration(durationMs(last))}`}>
        {pts.map((r, i) => {
          const h = Math.max(2, ((durationMs(r) ?? 0) / max) * (H - 4))
          return (
            <rect key={r.id} x={i * W + 1.5} y={H - h} width={W - 3} height={h} rx={1.5} fill={r.status === 'failed' ? 'var(--danger)' : 'currentColor'}>
              <title>{`${formatLima(r.started_at)} · ${formatDuration(durationMs(r))} · ${STATUS[r.status]?.[1] ?? r.status}`}</title>
            </rect>
          )
        })}
      </svg>
    </Panel>
  )
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

  const columns: Column<Run>[] = [
    { key: 'start', header: 'Inicio (Lima)', className: 'font-mono text-[12px] whitespace-nowrap', cell: (r) => formatLima(r.started_at) },
    { key: 'trigger', header: 'Disparo', cell: (r) => (r.trigger === 'cron' ? 'Programado' : 'Manual') },
    {
      key: 'status', header: 'Estado',
      cell: (r) => {
        const [kind, label] = STATUS[r.status] ?? (['neutral', r.status] as [Kind, string])
        const n = r.errors.length
        return (
          <span className="inline-flex items-center gap-2">
            <StatusBadge kind={kind}>{label}</StatusBadge>
            {n > 0 && <Meta icon={open === r.id ? CaretDown : CaretRight}>{n} {n === 1 ? 'error' : 'errores'}</Meta>}
          </span>
        )
      },
    },
    { key: 'kev', header: 'Catálogo KEV', className: 'font-mono text-[12px]', cell: (r) => <>{r.kev_catalog_version ?? '—'}{r.kev_total > 0 && <span className="text-muted"> · {r.kev_total}</span>}</> },
    { key: 'epss', header: 'EPSS', className: 'text-right tabular-nums', cell: (r) => r.epss_scored },
    { key: 'new', header: 'Nuevas en KEV', className: 'text-right tabular-nums', cell: (r) => r.new_matches },
    { key: 'alerts', header: 'Alertas', className: 'text-right tabular-nums', cell: (r) => r.alerts_created },
    { key: 'dur', header: 'Duración', className: 'text-right tabular-nums', cell: (r) => formatDuration(durationMs(r)) },
  ]

  return (
    <>
      <PageHeader
        title="Ejecuciones del workflow"
        subtitle="Cruce diario de KEV y EPSS con el inventario, orquestado por n8n. Un fallo de una fuente externa aparece aquí en rojo."
        actions={can('workflow', 'create') && <Button variant="primary" disabled={trigger.isPending} onClick={() => trigger.mutate()}>{trigger.isPending ? 'Iniciando…' : 'Ejecutar ahora'}</Button>}
      />
      {list.data && <DurationChart runs={list.data.items} />}
      <DataTable
        columns={columns}
        rows={list.data?.items}
        rowKey={(r) => r.id}
        loading={list.isPending}
        error={list.isError ? list.error.message : undefined}
        onRetry={() => void list.refetch()}
        skeletonRows={5}
        // Solo las ejecuciones con errores se expanden: el detalle del error está en la fila, no en otra pantalla.
        rowProps={(r) => (r.errors.length ? { ...rowOpen(() => setOpen(open === r.id ? null : r.id)), 'aria-expanded': open === r.id } : {})}
        expanded={(r) => open === r.id && (
          <div>
            <p className="mb-1 text-[12px] font-medium text-muted">Detalle del error</p>
            <ul className="space-y-1 text-[12px]">
              {r.errors.map((e, i) => <li key={i}><span className="font-mono font-medium">{e.node}</span>: {e.message} <span className="text-muted">({formatLima(e.at)})</span></li>)}
            </ul>
          </div>
        )}
        empty={<EmptyState title="Aún no hay ejecuciones" hint="La primera corre a las 06:00 (hora de Lima) cuando el workflow de n8n esté importado y activo." />}
      />
    </>
  )
}
