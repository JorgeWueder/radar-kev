import { CaretDown, CaretUp } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { Button, EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api } from '../lib/api'
import { formatDate, formatPct } from '../lib/format'

interface KevRow {
  cve_id: string; vendor_project: string; product: string; vulnerability_name: string; date_added: string
  due_date: string; ransomware_use: string; short_description: string; required_action: string; notes: string
  cwes: string[]; assets_affected: number; epss: number | null; percentile: number | null
}
interface KevList { items: KevRow[]; total: number; catalog_version: string | null; in_environment: number }

const PAGE = 50
type Sort = 'date_added' | 'due_date' | 'cve_id' | 'vendor_project'

export default function Kev() {
  const [search] = useSearchParams()
  const [f, setF] = useState({ q: search.get('q') ?? '', vendor: '', ransomware: false, in_environment: false, date_from: '', date_to: '' })
  const [sort, setSort] = useState<Sort>('date_added')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<string | null>(null)

  const params = { ...f, ransomware: f.ransomware || undefined, in_environment: f.in_environment || undefined, sort, direction: dir, limit: PAGE, offset: page * PAGE }
  const list = useQuery({ queryKey: ['kev', params], queryFn: () => api.get<KevList>('/kev', params) })
  const vendors = useQuery({ queryKey: ['kev-vendors'], queryFn: () => api.get<string[]>('/kev/vendors'), staleTime: 300_000 })

  const upd = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => { setF({ ...f, [k]: v }); setPage(0) }
  const sortBy = (s: Sort) => { if (s === sort) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(s); setDir('desc') } setPage(0) }
  const head = (s: Sort, label: string) => (
    <th className={th} aria-sort={sort === s ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button className="inline-flex items-center gap-1 hover:text-ink" onClick={() => sortBy(s)}>
        {label}{sort === s && (dir === 'asc' ? <CaretUp size={12} weight="bold" /> : <CaretDown size={12} weight="bold" />)}
      </button>
    </th>
  )
  const total = list.data?.total ?? 0

  return (
    <>
      <PageHeader
        title="Catálogo KEV"
        subtitle={list.data
          ? `Vulnerabilidades con explotación activa confirmada por CISA · versión ${list.data.catalog_version ?? '—'} · ${list.data.in_environment} presentes en su entorno`
          : 'Vulnerabilidades con explotación activa confirmada por CISA'}
      />
      <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-6">
        <Input aria-label="Buscar" placeholder="CVE, proveedor o producto" value={f.q} onChange={(e) => upd('q', e.target.value)} className="col-span-2" />
        <Select aria-label="Proveedor" value={f.vendor} onChange={(e) => upd('vendor', e.target.value)}>
          <option value="">Todos los proveedores</option>
          {vendors.data?.map((v) => <option key={v} value={v}>{v}</option>)}
        </Select>
        <Input aria-label="Agregado desde" type="date" value={f.date_from} onChange={(e) => upd('date_from', e.target.value)} />
        <Input aria-label="Agregado hasta" type="date" value={f.date_to} onChange={(e) => upd('date_to', e.target.value)} />
        <div className="flex flex-col justify-center gap-0.5 text-[13px]">
          <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={f.in_environment} onChange={(e) => upd('in_environment', e.target.checked)} /> En mi entorno</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={f.ransomware} onChange={(e) => upd('ransomware', e.target.checked)} /> Uso en ransomware</label>
        </div>
      </div>
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={6} rows={10} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="Sin resultados" hint={list.data.catalog_version ? 'Ninguna entrada coincide con los filtros.' : 'El catálogo aún no se ha descargado: se carga en la primera ejecución diaria.'} />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              {head('cve_id', 'CVE')}{head('vendor_project', 'Proveedor / producto')}{head('date_added', 'Agregado')}{head('due_date', 'Vence (CISA)')}
              <th className={`${th} text-right`}>EPSS</th><th className={th}>Ransomware</th><th className={th}>En mi entorno</th>
            </tr></thead>
            <tbody>
              {list.data.items.map((k) => (
                <Fragment key={k.cve_id}>
                  <tr className="cursor-pointer hover:bg-sunken" onClick={() => setOpen(open === k.cve_id ? null : k.cve_id)}>
                    <td className={`${td} font-mono text-[12px] font-medium whitespace-nowrap`}>{k.cve_id}</td>
                    <td className={td}><div className="font-medium">{k.vendor_project} · {k.product}</div><div className="max-w-md truncate text-[12px] text-muted">{k.vulnerability_name}</div></td>
                    <td className={`${td} whitespace-nowrap tabular-nums`}>{formatDate(k.date_added)}</td>
                    <td className={`${td} whitespace-nowrap tabular-nums`}>{formatDate(k.due_date)}</td>
                    <td className={`${td} text-right tabular-nums whitespace-nowrap`}>{formatPct(k.epss)}</td>
                    <td className={td}>{k.ransomware_use === 'Known' ? <StatusBadge kind="danger">Conocido</StatusBadge> : <span className="text-muted">—</span>}</td>
                    <td className={td}>{k.assets_affected > 0 ? <StatusBadge kind="danger">{k.assets_affected} {k.assets_affected === 1 ? 'activo' : 'activos'}</StatusBadge> : <span className="text-muted">—</span>}</td>
                  </tr>
                  {open === k.cve_id && (
                    <tr><td colSpan={7} className="border-b border-line bg-sunken px-4 py-3">
                      <div className="grid gap-3 text-[13px] md:grid-cols-2">
                        <div><p className="mb-0.5 text-[12px] font-medium text-muted">Descripción</p><p>{k.short_description}</p></div>
                        <div><p className="mb-0.5 text-[12px] font-medium text-muted">Acción requerida (CISA)</p><p>{k.required_action}</p></div>
                        {k.cwes.length > 0 && <div><p className="mb-0.5 text-[12px] font-medium text-muted">CWE</p><p className="font-mono text-[12px]">{k.cwes.join(', ')}</p></div>}
                        {k.notes && <div><p className="mb-0.5 text-[12px] font-medium text-muted">Notas</p><p className="break-words text-[12px]">{k.notes}</p></div>}
                      </div>
                    </td></tr>
                  )}
                </Fragment>
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
