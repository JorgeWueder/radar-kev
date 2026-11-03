import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button, EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDate, formatPct } from '../lib/format'
import { BAND, CRITICALITY, ENVIRONMENT, SLA, VULN_STATUS, criticalityKind } from '../lib/labels'

interface Vuln {
  id: string; cve_id: string; cvss_score: number | null; status: string; last_seen: string
  asset: { id: string; hostname: string; ip: string | null; criticality: number; environment: string }
  risk_score: number | null; risk_band: string | null; sla_due_date: string | null; kev_matched_at: string | null
  in_kev: boolean; kev_due_date: string | null; ransomware: boolean; epss: number | null; percentile: number | null; sla_state: string
}

const PAGE = 50

export default function Vulnerabilities() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [f, setF] = useState({ q: '', status: '', environment: '', kev: false, overdue: false })
  const [page, setPage] = useState(0)
  const params = { ...f, kev: f.kev || undefined, overdue: f.overdue || undefined, limit: PAGE, offset: page * PAGE }
  const list = useQuery({ queryKey: ['vulnerabilities', params], queryFn: () => api.get<{ items: Vuln[]; total: number }>('/vulnerabilities', params) })
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.patch(`/vulnerabilities/${id}`, { status }),
    onSuccess: () => { toast.success('Estado actualizado'); void qc.invalidateQueries({ queryKey: ['vulnerabilities'] }) },
    onError: (e: Error) => toast.error(e.message),
  })
  const set = (k: 'q' | 'status' | 'environment') => (e: { target: { value: string } }) => { setF({ ...f, [k]: e.target.value }); setPage(0) }
  const flag = (k: 'kev' | 'overdue') => (e: { target: { checked: boolean } }) => { setF({ ...f, [k]: e.target.checked }); setPage(0) }
  const total = list.data?.total ?? 0

  return (
    <>
      <PageHeader title="Vulnerabilidades" subtitle="Hallazgos por activo, ordenados por score de riesgo. KEV, EPSS y SLA se actualizan con el cruce diario." />
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Input aria-label="Buscar" placeholder="CVE u hostname" value={f.q} onChange={set('q')} className="col-span-2" />
        <Select aria-label="Estado" value={f.status} onChange={set('status')}>
          <option value="">Todos los estados</option>
          {Object.entries(VULN_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select aria-label="Entorno" value={f.environment} onChange={set('environment')}>
          <option value="">Todos los entornos</option>
          {Object.entries(ENVIRONMENT).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" className="accent-[var(--accent)]" checked={f.kev} onChange={flag('kev')} /> Solo en KEV</label>
        <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" className="accent-[var(--accent)]" checked={f.overdue} onChange={flag('overdue')} /> SLA vencido</label>
      </div>
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={8} rows={8} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="Sin hallazgos" hint={f.q || f.status || f.environment ? 'Ningún hallazgo coincide con los filtros.' : 'Importe un reporte de escáner para ver hallazgos aquí.'} />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              <th className={th}>CVE</th><th className={th}>Activo</th><th className={th}>Criticidad</th>
              <th className={th}>KEV</th><th className={`${th} text-right`}>EPSS</th><th className={`${th} text-right`}>CVSS</th>
              <th className={th}>Riesgo</th><th className={th}>SLA</th><th className={th}>Estado</th>
            </tr></thead>
            <tbody>
              {list.data.items.map((v) => (
                <tr key={v.id}>
                  <td className={`${td} font-mono text-[12px] font-medium whitespace-nowrap`}>{v.cve_id}</td>
                  <td className={td}><span className="font-mono text-[12px] whitespace-nowrap">{v.asset.hostname}</span><div className="text-[12px] text-muted">{ENVIRONMENT[v.asset.environment]}</div></td>
                  <td className={td}><StatusBadge kind={criticalityKind(v.asset.criticality)}>{CRITICALITY[v.asset.criticality]}</StatusBadge></td>
                  <td className={td}>{v.in_kev ? <StatusBadge kind="danger">{v.ransomware ? 'KEV · ransomware' : 'KEV'}</StatusBadge> : <span className="text-muted">—</span>}</td>
                  <td className={`${td} text-right tabular-nums whitespace-nowrap`}>{formatPct(v.epss)}</td>
                  <td className={`${td} text-right tabular-nums`}>{v.cvss_score ?? '—'}</td>
                  <td className={`${td} whitespace-nowrap`}>{v.risk_score === null || !v.risk_band ? <span className="text-muted">—</span> : <span className="inline-flex items-center gap-1.5"><span className="tabular-nums font-medium">{v.risk_score.toFixed(1)}</span><StatusBadge kind={BAND[v.risk_band][0]}>{BAND[v.risk_band][1]}</StatusBadge></span>}</td>
                  <td className={`${td} whitespace-nowrap`}><StatusBadge kind={SLA[v.sla_state][0]}>{SLA[v.sla_state][1]}</StatusBadge>{v.sla_due_date && v.sla_state !== 'no_aplica' && <div className="mt-0.5 text-[12px] tabular-nums text-muted">{formatDate(v.sla_due_date)}</div>}</td>
                  <td className={td}>
                    {can('vulnerabilities', 'edit') ? (
                      <Select aria-label={`Estado de ${v.cve_id} en ${v.asset.hostname}`} className="!h-7 !w-auto" value={v.status} onChange={(e) => setStatus.mutate({ id: v.id, status: e.target.value })}>
                        {Object.entries(VULN_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                      </Select>
                    ) : VULN_STATUS[v.status]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
