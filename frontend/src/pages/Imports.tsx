import { CheckCircle, DownloadSimple, UploadSimple } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button, EmptyState, ErrorState, PageHeader, Panel, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api, download, upload } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatLima } from '../lib/format'

interface Batch {
  id: string; source: string; filename: string; status: string; rows_ok: number; rows_error: number
  errors: { row: number; error: string }[]; summary: Record<string, number>; created_at: string; committed_at: string | null
}
interface Preview extends Batch { sample: { hostname: string; ip: string | null; cve_id: string; cvss_score: number | null }[]; hosts: number }

const SUMMARY_LABELS: Record<string, string> = {
  created_assets: 'Activos nuevos', created_vulnerabilities: 'Hallazgos nuevos',
  updated_vulnerabilities: 'Hallazgos actualizados', reopened: 'Reabiertos',
}

const STEPS = ['Subir archivo', 'Previsualizar', 'Confirmar']

/** Indicador de pasos: deja claro que primero se previsualiza y recién después se guarda. */
function Steps({ current }: { current: 0 | 1 | 2 }) {
  return (
    <ol className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]" aria-label="Pasos de la importación">
      {STEPS.map((label, i) => (
        <li key={label} aria-current={i === current ? 'step' : undefined} className={`flex items-center gap-2 ${i === current ? 'font-medium text-ink' : 'text-muted'}`}>
          <span className={`grid size-5 place-items-center rounded-full text-[11px] tabular-nums ${i < current ? 'bg-ink text-bg' : i === current ? 'border border-ink' : 'border border-line-strong'}`}>
            {i < current ? <CheckCircle size={13} weight="bold" aria-hidden /> : i + 1}
          </span>
          {label}
          {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-line-strong" aria-hidden />}
        </li>
      ))}
    </ol>
  )
}

export default function Imports() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [done, setDone] = useState<Batch | null>(null)
  const [error, setError] = useState('')

  const history = useQuery({ queryKey: ['imports'], queryFn: () => api.get<{ items: Batch[] }>('/imports') })

  const send = useMutation({
    mutationFn: (file: File) => upload<Preview>('/imports/preview', file),
    onSuccess: (p) => { setPreview(p); setDone(null); setError('') },
    onError: (e: Error) => { setPreview(null); setError(e.message) },
  })
  const commit = useMutation({
    mutationFn: (id: string) => api.post<Batch>(`/imports/${id}/commit`),
    onSuccess: (b) => {
      setDone(b); setPreview(null)
      toast.success('Importación aplicada')
      void qc.invalidateQueries({ queryKey: ['imports'] })
      void qc.invalidateQueries({ queryKey: ['assets'] })
      void qc.invalidateQueries({ queryKey: ['vulnerabilities'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const pick = (file: File | undefined) => {
    if (!file) return
    setError('')
    send.mutate(file)
    if (input.current) input.current.value = ''
  }

  return (
    <>
      <PageHeader title="Importación de hallazgos" subtitle="CSV genérico o reporte Nessus (.nessus). Se previsualiza antes de guardar nada." />
      {can('imports', 'create') && <Steps current={done ? 2 : preview ? 1 : 0} />}
      {can('imports', 'create') && (
        <Panel className="mb-4 p-4">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files[0]) }}
            className={`flex flex-col items-center gap-2 rounded-[20px] border-2 border-dashed px-4 py-8 text-center transition-[background-color,border-color] duration-150 ${dragging ? 'border-ink bg-sunken' : 'border-line-strong hover:border-ink hover:bg-sunken'}`}
          >
            <UploadSimple size={26} className={dragging ? 'text-ink' : 'text-muted'} aria-hidden />
            <p className="text-[13px]">{dragging ? 'Suelte el archivo para analizarlo' : <>Arrastre un archivo aquí o <button className="font-medium text-link underline underline-offset-2" onClick={() => input.current?.click()}>seleccione uno</button></>}</p>
            <p className="text-[12px] text-muted">.csv o .nessus · máximo 10 MB · hasta 20.000 filas</p>
            <input ref={input} type="file" accept=".csv,.nessus" className="sr-only" aria-label="Archivo de hallazgos" onChange={(e) => pick(e.target.files?.[0])} />
            <Button variant="ghost" onClick={() => void download('/imports/template.csv', {}, 'plantilla_hallazgos.csv')}><DownloadSimple size={15} /> Descargar plantilla CSV</Button>
          </div>
          {send.isPending && <p role="status" className="mt-3 text-[13px] text-muted">Analizando archivo…</p>}
          {error && <p role="alert" className="mt-3 rounded-md bg-danger-soft px-2.5 py-2 text-[13px] text-danger">{error}</p>}
        </Panel>
      )}

      {preview && (
        <Panel className="mb-4 border-2 !border-ink">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3">
            <div>
              <p className="text-[12px] font-medium text-muted">Paso 2 de 3 · Revise y confirme. Todavía no se guardó nada.</p>
              <p className="font-medium">{preview.filename}</p>
              <p className="text-[13px] text-muted">
                {preview.rows_ok} hallazgos válidos en {preview.hosts} equipos
                {preview.rows_error > 0 && <> · <span className="text-danger">{preview.rows_error} filas con error (se omiten)</span></>}
              </p>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => setPreview(null)}>Descartar</Button>
              <Button variant="primary" disabled={preview.rows_ok === 0 || commit.isPending} onClick={() => commit.mutate(preview.id)}>Confirmar importación</Button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>Hostname</th><th className={th}>IP</th><th className={th}>CVE</th><th className={`${th} text-right`}>CVSS</th></tr></thead>
              <tbody>
                {preview.sample.map((r) => (
                  <tr key={`${r.hostname}${r.cve_id}`}>
                    <td className={`${td} font-mono text-[12px]`}>{r.hostname}</td><td className={`${td} font-mono text-[12px]`}>{r.ip ?? '—'}</td>
                    <td className={`${td} font-mono text-[12px]`}>{r.cve_id}</td><td className={`${td} text-right tabular-nums`}>{r.cvss_score ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {preview.rows_ok > preview.sample.length && <p className="px-3 py-2 text-[12px] text-muted">Mostrando {preview.sample.length} de {preview.rows_ok} filas.</p>}
          </div>
          {preview.errors.length > 0 && (
            <div className="border-t border-line px-4 py-3">
              <p className="mb-1 text-[13px] font-medium">Errores por fila</p>
              <ul className="max-h-40 space-y-0.5 overflow-y-auto text-[12px]">
                {preview.errors.map((e) => <li key={`${e.row}${e.error}`}><span className="font-mono">Fila {e.row}</span>: {e.error}</li>)}
              </ul>
            </div>
          )}
        </Panel>
      )}

      {done && (
        <Panel className="mb-4 p-4" >
          <p className="mb-2 flex items-center gap-1.5 font-medium text-ok" role="status"><CheckCircle size={18} weight="bold" aria-hidden /> Importación aplicada: {done.filename}</p>
          <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {Object.entries(SUMMARY_LABELS).map(([k, label]) => (
              <div key={k}><dt className="text-[12px] text-muted">{label}</dt><dd className="text-[20px] font-semibold tabular-nums">{done.summary[k] ?? 0}</dd></div>
            ))}
          </dl>
          {(done.summary.created_assets ?? 0) > 0 && <p className="mt-3 text-[13px] text-muted">Los activos nuevos se crearon con criticidad Media y entorno Producción; complete sus datos en Activos.</p>}
        </Panel>
      )}

      <h2 className="mb-2 text-[14px] font-semibold">Historial</h2>
      <Panel className="overflow-x-auto">
        {history.isPending ? <Skeleton cols={5} rows={4} /> : history.isError ? (
          <ErrorState message={history.error.message} onRetry={() => void history.refetch()} />
        ) : history.data.items.length === 0 ? (
          <EmptyState title="Sin importaciones" hint="Aquí aparecerán los archivos cargados y su resultado." />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr><th className={th}>Fecha (Lima)</th><th className={th}>Archivo</th><th className={th}>Origen</th><th className={`${th} text-right`}>Válidas</th><th className={`${th} text-right`}>Con error</th><th className={th}>Estado</th></tr></thead>
            <tbody>
              {history.data.items.map((b) => (
                <tr key={b.id}>
                  <td className={`${td} font-mono text-[12px] whitespace-nowrap`}>{formatLima(b.created_at)}</td>
                  <td className={td}>{b.filename}</td><td className={td}>{b.source === 'nessus' ? 'Nessus' : 'CSV'}</td>
                  <td className={`${td} text-right tabular-nums`}>{b.rows_ok}</td><td className={`${td} text-right tabular-nums`}>{b.rows_error}</td>
                  <td className={td}><StatusBadge kind={b.status === 'committed' ? 'ok' : 'neutral'}>{b.status === 'committed' ? 'Aplicada' : 'Sin confirmar'}</StatusBadge></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  )
}
