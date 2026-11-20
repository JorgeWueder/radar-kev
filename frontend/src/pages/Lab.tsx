// Laboratorio de modelos (experimental): predice qué CVE entrarán a KEV. Fase 1: datos.
import { Flask } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { DatasetDetail } from '../components/lab/DatasetDetail'
import { JobProgress } from '../components/lab/JobProgress'
import { LabEvaluation } from '../components/lab/LabEvaluation'
import { LabExplain } from '../components/lab/LabExplain'
import { Training } from '../components/lab/Training'
import type { Dataset, Job } from '../components/lab/types'
import { num } from '../components/Descriptive'
import { Button, EmptyState, ErrorState, Field, Input, PageHeader, Panel, Select, Skeleton, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

const PHASES = ['Datos', 'Entrenamiento', 'Evaluación', 'Explicabilidad', 'Reportes', 'Inferencia', 'Optimización']
const READY_PHASES = 4 // fases ya implementadas
const STATUS: Record<Dataset['status'], ['ok' | 'warn' | 'danger' | 'neutral', string]> = {
  ready: ['ok', 'Listo'], building: ['neutral', 'Construyendo'], failed: ['danger', 'Falló'],
}
const HORIZONS = [30, 90, 180] as const

function NewDataset({ onStarted }: { onStarted: (r: { dataset_id: string; job_id: string }) => void }) {
  const [form, setForm] = useState({ name: 'KEV en 90 días', description: '', start: '2025-01-01', horizon_days: 90 as (typeof HORIZONS)[number], neg_rate: 0.05, seed: 7 })
  const create = useMutation({
    mutationFn: () => api.post<{ dataset_id: string; job_id: string }>('/ml/datasets', form),
    onSuccess: (r) => { toast.success('Construcción iniciada'); onStarted(r) },
    onError: (e) => toast.error((e as Error).message),
  })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
      <Field label="Nombre"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required minLength={3} /></Field>
      <Field label="Descripción (opcional)"><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Primera foto"><Input type="date" min="2024-11-01" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></Field>
        <Field label="Semilla"><Input type="number" min={0} value={form.seed} onChange={(e) => setForm({ ...form, seed: Number(e.target.value) })} className="tabular-nums" /></Field>
      </div>
      <div>
        <p className="mb-1 text-[12px] font-medium text-muted">Horizonte de la etiqueta</p>
        <div role="group" aria-label="Horizonte de la etiqueta" className="flex gap-1">
          {HORIZONS.map((h) => (
            <button key={h} type="button" aria-pressed={form.horizon_days === h} onClick={() => setForm({ ...form, horizon_days: h })}
              className={`h-8 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-11 ${form.horizon_days === h ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>{h} días</button>
          ))}
        </div>
      </div>
      <Field label="Muestreo de negativos">
        <Select value={form.neg_rate} onChange={(e) => setForm({ ...form, neg_rate: Number(e.target.value) })}>
          {[0.01, 0.02, 0.05, 0.1, 0.2].map((r) => <option key={r} value={r}>{num(r * 100, '%', 0)} de los CVE que no entran a KEV</option>)}
        </Select>
      </Field>
      <Button variant="primary" type="submit" disabled={create.isPending}>{create.isPending ? 'Iniciando…' : 'Construir dataset'}</Button>
      <p className="text-[12px] text-muted">La primera vez descarga EPSS, NVD y Exploit-DB (unos cientos de MB) y tarda varios minutos; después usa la caché.</p>
    </form>
  )
}

export default function Lab() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['ml-datasets'], queryFn: () => api.get<Dataset[]>('/ml/datasets') })
  const running = useQuery({ queryKey: ['ml-jobs-running'], queryFn: () => api.get<Job[]>('/ml/jobs', { kind: 'dataset', limit: 1 }) })
  const [picked, setSelected] = useState<string | null>(null)
  const [startedJob, setJobId] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [phase, setPhase] = useState(0)
  // Estado derivado (sin efectos): el dataset elegido o, si no, el primero listo; el trabajo lanzado aquí o uno en curso.
  const selected = picked ?? list.data?.find((d) => d.status === 'ready')?.id ?? list.data?.[0]?.id ?? null
  const live = running.data?.[0]
  const jobId = startedJob ?? (live && (live.status === 'running' || live.status === 'queued') && live.id !== dismissed ? live.id : null)

  return (
    <>
      <PageHeader title="Laboratorio de modelos"
        subtitle="Experimental: aprende a anticipar qué CVE entrarán a CISA KEV. Nada de aquí cambia la detección ni el score del radar." />
      <nav aria-label="Fases del laboratorio" className="mb-4">
        <ol className="flex flex-wrap gap-1">
          {PHASES.map((p, i) => {
            const ready = i < READY_PHASES
            const cls = `rounded-full px-3 py-1 text-[12px] ${phase === i ? 'bg-ink font-medium text-bg' : ready ? 'bg-sunken text-ink hover:bg-control' : 'bg-sunken text-muted'}`
            return (
              <li key={p}>
                {ready ? (
                  <button type="button" aria-current={phase === i ? 'step' : undefined} onClick={() => setPhase(i)} className={`${cls} transition-colors duration-150 pointer-coarse:py-2.5`}>{i + 1} · {p}</button>
                ) : <span className={cls} title="Próxima fase">{i + 1} · {p}<span className="sr-only"> (próxima fase)</span></span>}
              </li>
            )
          })}
        </ol>
      </nav>

      {phase === 1 ? <Training datasets={list.data ?? []} /> : phase === 2 ? <LabEvaluation datasets={list.data ?? []} /> : phase === 3 ? <LabExplain datasets={list.data ?? []} /> : (
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-4">
          {can('ml', 'create') && (
            <Panel className="p-4">
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-[14px] font-semibold">Nuevo dataset</h2>
                {!creating && !jobId && <Button onClick={() => setCreating(true)}>Configurar</Button>}
              </div>
              {jobId ? (
                <JobProgress jobId={jobId} onDone={(j) => {
                  void qc.invalidateQueries({ queryKey: ['ml-datasets'] })
                  if (j.target_id) { void qc.invalidateQueries({ queryKey: ['ml-dataset', j.target_id] }); setSelected(j.target_id) }
                  if (j.status === 'done') toast.success('Dataset listo')
                  window.setTimeout(() => { setJobId(null); setDismissed(j.id) }, 4000)
                }} />
              ) : creating ? (
                <NewDataset onStarted={(r) => { setCreating(false); setJobId(r.job_id); setSelected(r.dataset_id); void qc.invalidateQueries({ queryKey: ['ml-datasets'] }) }} />
              ) : <p className="text-[12px] text-muted">Arma fotos mensuales del universo de CVE con su etiqueta «entró a KEV» y variables solo del pasado.</p>}
            </Panel>
          )}
          <Panel className="p-2">
            <h2 className="px-2 pb-1 pt-2 text-[14px] font-semibold">Datasets</h2>
            {list.isPending ? <Skeleton cols={1} rows={3} /> : list.isError ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} /> : list.data.length === 0 ? (
              <EmptyState compact icon={Flask} title="Aún no hay datasets" hint={can('ml', 'create') ? 'Configure y construya el primero.' : 'Pida a un analista que construya uno.'} />
            ) : (
              <ul className="space-y-1">
                {list.data.map((d) => (
                  <li key={d.id}>
                    <button type="button" onClick={() => setSelected(d.id)} aria-current={selected === d.id ? 'true' : undefined}
                      className={`w-full rounded-lg px-3 py-2 text-left transition-colors duration-150 ${selected === d.id ? 'bg-sunken' : 'hover:bg-sunken'}`}>
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-[13px] font-medium">{d.name}</span>
                        <StatusBadge kind={STATUS[d.status][0]}>{STATUS[d.status][1]}</StatusBadge>
                      </span>
                      <span className="block text-[12px] text-muted tabular-nums">
                        {d.stats.rows ? `${d.stats.rows.toLocaleString('es-PE').replace(/[,.]/g, ' ')} filas · ${d.stats.positives} KEV · ` : ''}{d.params.horizon_days} días
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        {selected ? <DatasetDetail key={selected} id={selected} /> : (
          <Panel><EmptyState icon={Flask} title="Seleccione un dataset" hint="Aquí verá su resumen, validación, variables, muestra y metadata." /></Panel>
        )}
      </div>
      )}
    </>
  )
}
