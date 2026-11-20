// Fase 5 · Reportes del laboratorio: dataset, entrenamiento, evaluación y explicabilidad en PDF, Word (600 DPI) y Excel.
import { DownloadSimple } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { api, download } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { FORMAT_LABEL, type ReportFormat } from '../../lib/reports'
import { Button, EmptyState, Field, Panel, Select } from '../ui'
import type { Model } from './Training'
import type { Dataset } from './types'

type Key = 'ml_dataset' | 'ml_training' | 'ml_evaluation' | 'ml_explain'
const REPORTS: { key: Key; phase: string; title: string; description: string; needs: 'dataset' | 'model'; requires?: string }[] = [
  { key: 'ml_dataset', phase: '1 · Datos', title: 'Dataset', description: 'Partición 70/15/15, validación, estadística de las variables, variables descartadas por fuga, fuentes y licencias.', needs: 'dataset' },
  { key: 'ml_training', phase: '2 · Entrenamiento', title: 'Entrenamiento', description: 'Configuración, espacio de hiperparámetros, CV anidada 5×3 por pliegue y evolución de las pruebas de Optuna.', needs: 'model' },
  { key: 'ml_evaluation', phase: '3 · Evaluación', title: 'Evaluación', description: 'Métricas en prueba, matrices de confusión, curvas ROC y PR, pruebas estadísticas y estabilidad mensual.', needs: 'dataset', requires: 'Requiere haber calculado la evaluación en la fase 3.' },
  { key: 'ml_explain', phase: '4 · Explicabilidad', title: 'Explicabilidad', description: 'Equivalencias con el Promptuario, importancia, dependencia parcial, mapa de interacción y casos explicados.', needs: 'model', requires: 'Requiere haber calculado las explicaciones de ese modelo en la fase 4.' },
]

export function LabReports({ datasets }: { datasets: Dataset[] }) {
  const { can } = useAuth()
  const ready = datasets.filter((d) => d.status === 'ready')
  const preferred = ready.find((d) => !d.tags.includes('descartado')) ?? ready[0]
  const [dsId, setDsId] = useState<string | null>(null)
  const datasetId = dsId ?? preferred?.id ?? null
  const models = useQuery({ queryKey: ['ml-models', datasetId], queryFn: () => api.get<Model[]>('/ml/models', { dataset_id: datasetId ?? '' }), enabled: !!datasetId })
  const readyModels = (models.data ?? []).filter((m) => m.status === 'ready')
  const [picked, setPicked] = useState<string | null>(null)
  const modelId = picked ?? readyModels[0]?.id ?? null
  const [op, setOp] = useState<1 | 5>(1)
  const [busy, setBusy] = useState<string | null>(null)
  const canExport = can('reports', 'export')
  if (!ready.length) return <Panel><EmptyState title="Aún no hay datasets listos" hint="Construya uno en la fase 1 · Datos." /></Panel>

  const generate = async (key: Key, needs: 'dataset' | 'model', fmt: ReportFormat) => {
    const params = { fmt, ...(needs === 'dataset' ? { dataset_id: datasetId ?? undefined } : { model_id: modelId ?? undefined }), ...(key === 'ml_evaluation' ? { op } : {}) }
    setBusy(`${key}-${fmt}`)
    try {
      await download(`/reports/${key}`, params, `radar_${key}.${fmt}`, 'POST')
      toast.success(`${FORMAT_LABEL[fmt]} generado`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4">
      <Panel className="flex flex-wrap items-end gap-4 p-4">
        <div className="w-64"><Field label="Dataset"><Select value={datasetId ?? ''} onChange={(e) => { setDsId(e.target.value); setPicked(null) }}>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field></div>
        <div className="w-80"><Field label="Modelo (reportes de entrenamiento y explicabilidad)"><Select value={modelId ?? ''} onChange={(e) => setPicked(e.target.value)} disabled={!readyModels.length}>{readyModels.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field></div>
        <div>
          <p className="mb-1 text-[12px] font-medium text-muted">Punto de operación (evaluación)</p>
          <div role="group" aria-label="Punto de operación" className="flex gap-1">
            {([1, 5] as const).map((v) => (
              <button key={v} type="button" aria-pressed={op === v} onClick={() => setOp(v)}
                className={`h-8 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-11 ${op === v ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>Revisar el {v} %</button>
            ))}
          </div>
        </div>
      </Panel>
      <Panel className="divide-y divide-line">
        {REPORTS.map((r) => {
          const missing = r.needs === 'model' && !modelId
          return (
            <div key={r.key} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0 flex-1 basis-72">
                <p className="font-medium">{r.title} <span className="text-[12px] font-normal text-muted">· fase {r.phase}</span></p>
                <p className="text-[13px] text-muted">{r.description}</p>
                {r.requires && <p className="text-[12px] text-muted">{r.requires}</p>}
              </div>
              <div className="flex shrink-0 gap-2">
                {(['pdf', 'docx', 'xlsx'] as ReportFormat[]).map((f) => (
                  <Button key={f} disabled={!canExport || busy !== null || missing} onClick={() => void generate(r.key, r.needs, f)} aria-label={`${r.title} en ${FORMAT_LABEL[f]}`}>
                    <DownloadSimple size={15} /> {busy === `${r.key}-${f}` ? 'Generando…' : FORMAT_LABEL[f]}
                  </Button>
                ))}
              </div>
            </div>
          )
        })}
      </Panel>
      <p className="text-[12px] text-muted">
        PDF con gráficos vectoriales, Word con figuras a 600 DPI y Excel con gráficos nativos. Cada tabla y figura trae su «Cómo leerla». Cada exportación queda en la bitácora.
        {!canExport && ' Su rol puede ver el laboratorio pero no exportar reportes.'}
      </p>
    </div>
  )
}
