import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button, EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatLima } from '../lib/format'
import { CRITICALITY, ENVIRONMENT, VULN_STATUS, criticalityKind } from '../lib/labels'

interface Vuln {
  id: string; cve_id: string; cvss_score: number | null; status: string; last_seen: string
  asset: { id: string; hostname: string; ip: string | null; criticality: number; environment: string }
  risk_score: number | null; risk_band: string | null; sla_due_date: string | null; kev_matched_at: string | null
}

const PAGE = 50

export default function Vulnerabilities() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [f, setF] = useState({ q: '', status: '', environment: '' })
  const [page, setPage] = useState(0)
  const params = { ...f, limit: PAGE, offset: page * PAGE }
  const list = useQuery({ queryKey: ['vulnerabilities', params], queryFn: () => api.get<{ items: Vuln[]; total: number }>('/vulnerabilities', params) })
  const setStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.patch(`/vulnerabilities/${id}`, { status }),
    onSuccess: () => { toast.success('Estado actualizado'); void qc.invalidateQueries({ queryKey: ['vulnerabilities'] }) },
    onError: (e: Error) => toast.error(e.message),
  })
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => { setF({ ...f, [k]: e.target.value }); setPage(0) }
  const total = list.data?.total ?? 0

  return (
    <>
      <PageHeader title="Vulnerabilidades" subtitle="Hallazgos por activo. La pertenencia a KEV, EPSS y el score de riesgo se calculan en el cruce diario (fase 3)." />
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
      </div>
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={6} rows={8} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="Sin hallazgos" hint={f.q || f.status || f.environment ? 'Ningún hallazgo coincide con los filtros.' : 'Importe un reporte de escáner para ver hallazgos aquí.'} />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              <th className={th}>CVE</th><th className={th}>Activo</th><th className={th}>Criticidad</th>
              <th className={`${th} text-right`}>CVSS</th><th className={`${th} text-right`}>Riesgo</th><th className={th}>Estado</th><th className={th}>Última vez visto</th>
            </tr></thead>
            <tbody>
              {list.data.items.map((v) => (
                <tr key={v.id}>
                  <td className={`${td} font-mono text-[12px] font-medium whitespace-nowrap`}>{v.cve_id}</td>
                  <td className={td}><span className="font-mono text-[12px] whitespace-nowrap">{v.asset.hostname}</span><div className="text-[12px] text-muted">{ENVIRONMENT[v.asset.environment]}</div></td>
                  <td className={td}><StatusBadge kind={criticalityKind(v.asset.criticality)}>{CRITICALITY[v.asset.criticality]}</StatusBadge></td>
                  <td className={`${td} text-right tabular-nums`}>{v.cvss_score ?? '—'}</td>
                  <td className={`${td} text-right tabular-nums`}>{v.risk_score ?? '—'}</td>
                  <td className={td}>
                    {can('vulnerabilities', 'edit') ? (
                      <Select aria-label={`Estado de ${v.cve_id} en ${v.asset.hostname}`} className="!h-7 !w-auto" value={v.status} onChange={(e) => setStatus.mutate({ id: v.id, status: e.target.value })}>
                        {Object.entries(VULN_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                      </Select>
                    ) : VULN_STATUS[v.status]}
                  </td>
                  <td className={`${td} font-mono text-[12px] whitespace-nowrap`}>{formatLima(v.last_seen)}</td>
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
