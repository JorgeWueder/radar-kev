import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'

import { Button, rowToggle, EmptyState, ErrorState, Panel, Select, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api } from '../lib/api'
import { formatLima } from '../lib/format'
import type { Kind } from '../lib/labels'

interface Interaction {
  id: string; created_at: string; user: string | null; feature: string; engine: string; provider: string; model: string
  status: string; tokens_in: number | null; tokens_out: number | null; latency_ms: number; prompt: string
  sources: Record<string, unknown>; error: string | null
}

const FEATURE: Record<string, string> = { enrich: 'Enriquecer ticket', assistant: 'Asistente', exec_summary: 'Resumen ejecutivo' }
const STATUS: Record<string, [Kind, string]> = { ok: ['ok', 'Correcta'], error: ['danger', 'Error'], ungrounded: ['warn', 'Descartada'] }
const PAGE = 30

/** Registro de uso de IA: usuario, prompt, fuentes, modelo, tokens y latencia de cada llamada. */
export default function AiLog() {
  const [feature, setFeature] = useState('')
  const [page, setPage] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const list = useQuery({
    queryKey: ['ai-log', feature, page],
    queryFn: () => api.get<{ items: Interaction[]; total: number }>('/ai/interactions', { feature, limit: PAGE, offset: page * PAGE }),
  })
  const total = list.data?.total ?? 0
  return (
    <>
      <div className="mb-3 max-w-xs">
        <Select aria-label="Función de IA" value={feature} onChange={(e) => { setFeature(e.target.value); setPage(0) }}>
          <option value="">Todas las funciones</option>
          {Object.entries(FEATURE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </div>
      <Panel className="overflow-x-auto">
        {list.isPending ? <Skeleton cols={7} rows={6} /> : list.isError ? (
          <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />
        ) : list.data.items.length === 0 ? (
          <EmptyState title="Sin uso de IA registrado" hint="Cada enriquecimiento, consulta del asistente y resumen ejecutivo queda aquí." />
        ) : (
          <table className="w-full text-[13px]">
            <thead><tr>
              <th className={th}>Fecha (Lima)</th><th className={th}>Usuario</th><th className={th}>Función</th><th className={th}>Motor / modelo</th>
              <th className={th}>Estado</th><th className={`${th} text-right`}>Tokens (ent. / sal.)</th><th className={`${th} text-right`}>Latencia</th>
            </tr></thead>
            <tbody>
              {list.data.items.map((i) => {
                const [k, l] = STATUS[i.status] ?? ['neutral', i.status]
                return (
                  <Fragment key={i.id}>
                    <tr {...rowToggle(open === i.id, () => setOpen(open === i.id ? null : i.id))}>
                      <td className={`${td} font-mono text-[12px] whitespace-nowrap`}>{formatLima(i.created_at)}</td>
                      <td className={td}>{i.user ?? <span className="text-muted">Sistema (n8n)</span>}</td>
                      <td className={td}>{FEATURE[i.feature] ?? i.feature}</td>
                      <td className={td}><span className="font-mono text-[12px]">{i.engine} · {i.provider}/{i.model}</span></td>
                      <td className={td}><StatusBadge kind={k}>{l}</StatusBadge></td>
                      <td className={`${td} text-right tabular-nums`}>{i.tokens_in ?? '—'} / {i.tokens_out ?? '—'}</td>
                      <td className={`${td} text-right tabular-nums whitespace-nowrap`}>{(i.latency_ms / 1000).toFixed(1)} s</td>
                    </tr>
                    {open === i.id && (
                      <tr><td colSpan={7} className="border-b border-line bg-sunken px-4 py-3">
                        {i.error && <p className="mb-2 text-[12px] text-danger">{i.error}</p>}
                        <p className="mb-1 text-[12px] font-medium text-muted">Fuentes usadas</p>
                        <pre className="mb-2 max-h-40 overflow-auto font-mono text-[12px]">{JSON.stringify(i.sources, null, 2)}</pre>
                        <p className="mb-1 text-[12px] font-medium text-muted">Prompt</p>
                        <pre className="max-h-56 overflow-auto whitespace-pre-wrap font-mono text-[12px]">{i.prompt}</pre>
                      </td></tr>
                    )}
                  </Fragment>
                )
              })}
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
