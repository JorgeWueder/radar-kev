import { DownloadSimple } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button, ErrorState, Field, Input, PageHeader, Panel, Skeleton } from '../components/ui'
import { api, download } from '../lib/api'
import { useAuth } from '../lib/auth'
import { FORMAT_LABEL, defaultPeriod, reportError, reportParams, type ReportDef, type ReportFormat } from '../lib/reports'

export default function Reports() {
  const { can } = useAuth()
  const catalog = useQuery({ queryKey: ['report-catalog'], queryFn: () => api.get<ReportDef[]>('/reports/catalog') })
  const [period, setPeriod] = useState(defaultPeriod())
  const [cve, setCve] = useState('')
  const [ai, setAi] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

  const canExport = can('reports', 'export')
  const canAi = can('ai', 'view')

  const generate = async (def: ReportDef, fmt: ReportFormat) => {
    const problem = reportError(def, period, cve)
    if (problem) return toast.error(problem)
    setBusy(`${def.key}-${fmt}`)
    try {
      await download(`/reports/${def.key}`, reportParams(def, fmt, period, cve, ai), `radar_${def.key}.${fmt}`, 'POST')
      toast.success(`${def.title}: ${FORMAT_LABEL[fmt]} generado`)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const group = (kind: 'operational' | 'management', title: string, hint: string) => {
    const items = catalog.data?.filter((r) => r.kind === kind) ?? []
    return (
      <section className="mb-6" aria-labelledby={`g-${kind}`}>
        <h2 id={`g-${kind}`} className="text-[14px] font-semibold">{title}</h2>
        <p className="mb-2 text-[12px] text-muted">{hint}</p>
        <Panel className="divide-y divide-line">
          {items.map((r) => (
            <div key={r.key} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
              <div className="min-w-0 flex-1 basis-64">
                <p className="font-medium">{r.title}</p>
                <p className="text-[13px] text-muted">{r.description}</p>
                {r.needs_cve && (
                  <div className="mt-2 max-w-xs"><Field label="CVE del reporte"><Input value={cve} placeholder="CVE-2021-44228" onChange={(e) => setCve(e.target.value)} className="font-mono" /></Field></div>
                )}
              </div>
              <div className="flex shrink-0 gap-2">
                {(['pdf', 'docx', 'xlsx'] as ReportFormat[]).map((f) => (
                  <Button key={f} disabled={!canExport || busy !== null} onClick={() => void generate(r, f)} aria-label={`${r.title} en ${FORMAT_LABEL[f]}`}>
                    <DownloadSimple size={15} /> {busy === `${r.key}-${f}` ? 'Generando…' : FORMAT_LABEL[f]}
                  </Button>
                ))}
              </div>
            </div>
          ))}
        </Panel>
      </section>
    )
  }

  return (
    <>
      <PageHeader title="Reportes" subtitle="Operacionales y de gestión, en PDF, Word y Excel. Cada exportación queda en la bitácora." />
      <Panel className="mb-6 flex flex-wrap items-end gap-3 p-4">
        <Field label="Desde (reportes de gestión)"><Input type="date" value={period.from} max={period.to} onChange={(e) => setPeriod({ ...period, from: e.target.value })} /></Field>
        <Field label="Hasta"><Input type="date" value={period.to} onChange={(e) => setPeriod({ ...period, to: e.target.value })} /></Field>
        <label className={`flex items-center gap-1.5 pb-1.5 text-[13px] ${canAi ? '' : 'opacity-50'}`} title={canAi ? undefined : 'Su rol no puede usar la IA'}>
          <input type="checkbox" className="accent-[var(--accent)]" checked={ai && canAi} disabled={!canAi} onChange={(e) => setAi(e.target.checked)} />
          Incluir resumen ejecutivo generado por IA (reportes de gestión)
        </label>
      </Panel>
      {catalog.isPending ? <Panel><Skeleton cols={3} rows={6} /></Panel> : catalog.isError ? (
        <Panel><ErrorState message={catalog.error.message} onRetry={() => void catalog.refetch()} /></Panel>
      ) : (
        <>
          {group('operational', 'Operacionales', 'Situación actual: qué hay abierto, qué venció y qué hacer.')}
          {group('management', 'De gestión', 'Tendencia, tiempos de remediación y cumplimiento en el periodo elegido.')}
        </>
      )}
      {!canExport && <p className="text-[13px] text-muted">Su rol puede consultar el catálogo pero no exportar reportes.</p>}
    </>
  )
}
