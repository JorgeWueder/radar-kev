import { CaretDown, CaretUp, HardDrives, Skull } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { KevDrawer } from '../components/detail'
import { DataTable, Meta, Pagination, rowOpen, type Column } from '../components/kit'
import { EmptyState, Input, PageHeader, Select } from '../components/ui'
import { api } from '../lib/api'
import { formatDate, formatPct } from '../lib/format'
import type { KevRow } from '../lib/types'

interface KevList { items: KevRow[]; total: number; catalog_version: string | null; in_environment: number }

const PAGE = 50
type Sort = 'date_added' | 'due_date' | 'cve_id' | 'vendor_project'

export default function Kev() {
  const [search] = useSearchParams()
  const [f, setF] = useState({ q: search.get('q') ?? '', vendor: '', ransomware: false, in_environment: false, date_from: '', date_to: '' })
  const [sort, setSort] = useState<Sort>('date_added')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [sel, setSel] = useState<KevRow | null>(null)

  const params = { ...f, ransomware: f.ransomware || undefined, in_environment: f.in_environment || undefined, sort, direction: dir, limit: PAGE, offset: page * PAGE }
  const list = useQuery({ queryKey: ['kev', params], queryFn: () => api.get<KevList>('/kev', params) })
  const vendors = useQuery({ queryKey: ['kev-vendors'], queryFn: () => api.get<string[]>('/kev/vendors'), staleTime: 300_000 })

  const upd = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => { setF({ ...f, [k]: v }); setPage(0) }
  const sortBy = (s: Sort) => { if (s === sort) setDir(dir === 'asc' ? 'desc' : 'asc'); else { setSort(s); setDir('desc') } setPage(0) }
  const sortHeader = (s: Sort, label: string) => (
    <button className="inline-flex items-center gap-1 hover:text-ink" onClick={() => sortBy(s)}>
      {label}{sort === s && (dir === 'asc' ? <CaretUp size={12} weight="bold" /> : <CaretDown size={12} weight="bold" />)}
    </button>
  )
  const aria = (s: Sort) => (sort === s ? (dir === 'asc' ? 'ascending' : 'descending') : 'none') as 'ascending' | 'descending' | 'none'
  const total = list.data?.total ?? 0

  const columns: Column<KevRow>[] = [
    { key: 'cve', header: sortHeader('cve_id', 'CVE'), ariaSort: aria('cve_id'), className: 'font-mono text-[12px] font-medium whitespace-nowrap', cell: (k) => k.cve_id },
    { key: 'vendor', header: sortHeader('vendor_project', 'Proveedor / producto'), ariaSort: aria('vendor_project'), cell: (k) => <><div className="font-medium">{k.vendor_project} · {k.product}</div><div className="max-w-md truncate text-[12px] text-muted">{k.vulnerability_name}</div></> },
    { key: 'added', header: sortHeader('date_added', 'Agregado'), ariaSort: aria('date_added'), className: 'whitespace-nowrap tabular-nums', cell: (k) => formatDate(k.date_added) },
    { key: 'due', header: sortHeader('due_date', 'Vence (CISA)'), ariaSort: aria('due_date'), className: 'whitespace-nowrap tabular-nums', cell: (k) => formatDate(k.due_date) },
    { key: 'epss', header: 'EPSS', className: 'text-right tabular-nums whitespace-nowrap', cell: (k) => formatPct(k.epss) },
    { key: 'ransom', header: 'Ransomware', cell: (k) => (k.ransomware_use === 'Known' ? <Meta icon={Skull}>Conocido</Meta> : <span className="text-muted">—</span>) },
    { key: 'env', header: 'En mi entorno', cell: (k) => (k.assets_affected > 0 ? <Meta icon={HardDrives}>{k.assets_affected} {k.assets_affected === 1 ? 'activo' : 'activos'}</Meta> : <span className="text-muted">—</span>) },
  ]

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
      <DataTable
        columns={columns}
        rows={list.data?.items}
        rowKey={(k) => k.cve_id}
        loading={list.isPending}
        error={list.isError ? list.error.message : undefined}
        onRetry={() => void list.refetch()}
        skeletonRows={10}
        // Las filas con activos propios afectados se resaltan: son las que importan en este entorno.
        rowProps={(k) => rowOpen(() => setSel(k), k.assets_affected > 0 ? 'bg-sunken' : '')}
        empty={<EmptyState title="Sin resultados" hint={list.data?.catalog_version ? 'Ninguna entrada coincide con los filtros.' : 'El catálogo aún no se ha descargado: se carga en la primera ejecución diaria.'} />}
      />
      <Pagination page={page} total={total} pageSize={PAGE} onPage={setPage} />
      <KevDrawer k={sel} onClose={() => setSel(null)} />
    </>
  )
}
