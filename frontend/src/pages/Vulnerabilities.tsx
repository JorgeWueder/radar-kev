import { Target, Warning } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { VulnDrawer } from '../components/detail'
import { DataTable, Meta, Pagination, rowOpen, stop, type Column } from '../components/kit'
import { EmptyState, Input, PageHeader, Select, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatDate, formatPct } from '../lib/format'
import type { Vuln } from '../lib/types'
import { BAND, CRITICALITY, ENVIRONMENT, SLA, VULN_STATUS } from '../lib/labels'

const PAGE = 50

export default function Vulnerabilities() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [search] = useSearchParams()
  const [f, setF] = useState({ q: '', status: '', environment: '', kev: search.get('kev') === '1', overdue: search.get('overdue') === '1' })
  const [page, setPage] = useState(0)
  const [sel, setSel] = useState<Vuln | null>(null)
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

  const columns: Column<Vuln>[] = [
    { key: 'cve', header: 'CVE', className: 'font-mono text-[12px] font-medium whitespace-nowrap', cell: (v) => v.cve_id },
    { key: 'asset', header: 'Activo', cell: (v) => <><span className="font-mono text-[12px] whitespace-nowrap">{v.asset.hostname}</span><div className="text-[12px] text-muted">{ENVIRONMENT[v.asset.environment]}</div></> },
    { key: 'crit', header: 'Criticidad', cell: (v) => <Meta>{CRITICALITY[v.asset.criticality]}</Meta> },
    { key: 'kev', header: 'KEV', cell: (v) => (v.in_kev ? <Meta icon={Target}>{v.ransomware ? 'KEV · ransomware' : 'KEV'}</Meta> : <span className="text-muted">—</span>) },
    { key: 'epss', header: 'EPSS', className: 'text-right tabular-nums whitespace-nowrap', cell: (v) => formatPct(v.epss) },
    { key: 'cvss', header: 'CVSS', className: 'text-right tabular-nums', cell: (v) => v.cvss_score ?? '—' },
    {
      key: 'risk', header: 'Riesgo', className: 'whitespace-nowrap',
      cell: (v) => (v.risk_score === null || !v.risk_band ? <span className="text-muted">—</span> : <span className="inline-flex items-center gap-1.5"><span className="tabular-nums font-medium">{v.risk_score.toFixed(1)}</span><StatusBadge kind={BAND[v.risk_band][0]}>{BAND[v.risk_band][1]}</StatusBadge></span>),
    },
    {
      key: 'sla', header: 'SLA', className: 'whitespace-nowrap',
      cell: (v) => <><Meta icon={v.sla_state === 'vencido' ? Warning : undefined} alert={v.sla_state === 'vencido'}>{SLA[v.sla_state][1]}</Meta>{v.sla_due_date && v.sla_state !== 'no_aplica' && <div className="mt-0.5 text-[12px] tabular-nums text-muted">{formatDate(v.sla_due_date)}</div>}</>,
    },
    {
      key: 'status', header: 'Estado',
      cell: (v) => (can('vulnerabilities', 'edit') ? (
        <Select aria-label={`Estado de ${v.cve_id} en ${v.asset.hostname}`} className="!h-7 !w-auto" value={v.status} onClick={stop} onKeyDown={stop} onChange={(e) => setStatus.mutate({ id: v.id, status: e.target.value })}>
          {Object.entries(VULN_STATUS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
      ) : VULN_STATUS[v.status]),
    },
  ]

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
      <DataTable
        columns={columns}
        rows={list.data?.items}
        rowKey={(v) => v.id}
        rowProps={(v) => rowOpen(() => setSel(v))}
        loading={list.isPending}
        error={list.isError ? list.error.message : undefined}
        onRetry={() => void list.refetch()}
        skeletonRows={8}
        empty={<EmptyState title="Sin hallazgos" hint={f.q || f.status || f.environment ? 'Ningún hallazgo coincide con los filtros.' : 'Importe un reporte de escáner para ver hallazgos aquí.'} />}
      />
      <Pagination page={page} total={total} pageSize={PAGE} onPage={setPage} />
      <VulnDrawer v={sel} onClose={() => setSel(null)} />
    </>
  )
}
