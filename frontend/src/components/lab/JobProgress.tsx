// Monitoreo en vivo de un trabajo del laboratorio (dataset, entrenamiento…).
import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { api } from '../../lib/api'
import { formatLima } from '../../lib/format'
import { Skeleton } from '../ui'
import type { Job } from './types'

/** Monitoreo en vivo de un trabajo: barra de progreso y últimos pasos (consulta cada 1,5 s mientras corre). */
export function JobProgress({ jobId, onDone }: { jobId: string; onDone?: (j: Job) => void }) {
  const q = useQuery({
    queryKey: ['ml-job', jobId],
    queryFn: () => api.get<Job>(`/ml/jobs/${jobId}`),
    refetchInterval: (query) => (query.state.data && query.state.data.status !== 'running' && query.state.data.status !== 'queued' ? false : 1500),
  })
  const j = q.data
  const finished = j && (j.status === 'done' || j.status === 'failed')
  useEffect(() => { if (finished && j) onDone?.(j) }, [finished]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!j) return <Skeleton cols={1} rows={2} />
  return (
    <div aria-live="polite">
      <div className="flex items-center justify-between text-[13px]">
        <span className="font-medium">{j.status === 'failed' ? 'Falló' : j.status === 'done' ? 'Terminado' : 'En curso'} · {j.message}</span>
        <span className="tabular-nums text-muted">{j.progress} %</span>
      </div>
      <div className="mt-1 h-2 rounded-full bg-sunken" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={j.progress} aria-label="Avance del trabajo">
        <div className={`h-2 rounded-full transition-[width] duration-300 ${j.status === 'failed' ? 'bg-danger' : 'bg-accent'}`} style={{ width: `${j.progress}%` }} />
      </div>
      <ol className="mt-2 max-h-32 space-y-0.5 overflow-y-auto text-[12px] text-muted">
        {[...j.log].reverse().slice(0, 8).map((e) => <li key={`${e.t}-${e.msg}`} className="tabular-nums">{formatLima(e.t).slice(-8)} · {e.msg}</li>)}
      </ol>
    </div>
  )
}

