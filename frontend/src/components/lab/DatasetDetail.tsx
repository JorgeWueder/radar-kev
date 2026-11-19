// Detalle de un dataset del laboratorio (Fase 1): resumen, validación, variables, muestra y metadata.
import { CheckCircle, Info, Warning } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { formatDate, formatLima } from '../../lib/format'
import { num } from '../Descriptive'
import { Meta, Tabs } from '../kit'
import { Button, ErrorState, Field, Input, Panel, Select, Skeleton, Textarea, td, th } from '../ui'
import type { Check, Dataset, Profile } from './types'

type Tab = 'resumen' | 'validacion' | 'variables' | 'muestra' | 'metadata'
const TABS: { id: Tab; label: string }[] = [
  { id: 'resumen', label: 'Resumen' }, { id: 'validacion', label: 'Validación' }, { id: 'variables', label: 'Variables' },
  { id: 'muestra', label: 'Muestra' }, { id: 'metadata', label: 'Metadata' },
]
const int = (n: number | undefined) => (n ?? 0).toLocaleString('es-PE').replace(/[,.]/g, ' ')
/** Decimales según la magnitud: días o conteos sin decimales, puntajes con 1 o 2, probabilidades con 3 o 4. */
export const smart = (n: number | null | undefined) =>
  n === null || n === undefined ? '—' : Math.abs(n) >= 100 ? int(Math.round(n)) : num(n, '', Math.abs(n) >= 10 ? 1 : Math.abs(n) >= 1 ? 2 : n === 0 ? 0 : 4)

function How({ children }: { children: string }) {
  return <details className="mt-1 text-[12px] text-muted"><summary className="cursor-pointer select-none hover:text-ink">Cómo leerla</summary><p className="mt-1 max-w-prose">{children}</p></details>
}

const ICON = { ok: [CheckCircle, 'text-muted', 'Correcto'], warn: [Warning, 'text-warn', 'Aviso'], info: [Info, 'text-muted', 'Información'] } as const
function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="divide-y divide-line">
      {checks.map((c) => {
        const [Icon, tone, word] = ICON[c.status]
        return (
          <li key={c.key} className="grid grid-cols-[18px_1fr] gap-2 py-2 text-[13px]">
            <Icon size={16} weight={c.status === 'warn' ? 'bold' : 'regular'} className={`mt-0.5 ${tone}`} aria-label={word} />
            <span><span className="font-medium">{c.label}.</span> {c.detail}</span>
          </li>
        )
      })}
    </ul>
  )
}

function Summary({ p }: { p: Profile }) {
  const o = p.overview
  const maxPos = Math.max(1, ...p.snapshots.map((s) => s.positives))
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] sm:grid-cols-3 lg:grid-cols-6">
        {([['Filas', int(o.rows)], ['Entraron a KEV', int(o.positives)], ['Fotos mensuales', String(o.snapshots)], ['CVE distintos', int(o.cves)],
          ['Universo estimado', int(o.universe_estimate)], ['Proporción de KEV', num(o.prevalence_pct, '%', 3)]] as const).map(([k, v]) => (
          <div key={k}><dt className="text-[12px] text-muted">{k}</dt><dd className="text-[17px] font-semibold tabular-nums">{v}</dd></div>
        ))}
      </dl>
      <ul className="list-disc space-y-1 pl-5 text-[13px]">{p.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>
      <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Partición temporal 70/15/15</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>Partición</th><th className={th}>Fotos</th><th className={`${th} text-right`}>Filas</th><th className={`${th} text-right`}>KEV</th><th className={`${th} text-right`}>Proporción</th></tr></thead>
              <tbody>
                {p.splits.map((s) => (
                  <tr key={s.split}>
                    <td className={td}>{s.label}</td>
                    <td className={`${td} tabular-nums`}>{s.snapshots} <span className="text-muted">({formatDate(s.from)} a {formatDate(s.to)})</span></td>
                    <td className={`${td} text-right tabular-nums`}>{int(s.rows)}</td>
                    <td className={`${td} text-right tabular-nums`}>{s.positives}</td>
                    <td className={`${td} text-right tabular-nums`}>{num(s.prevalence_pct, '%', 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <How>{p.how_to_read.splits}</How>
        </div>
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Entradas a KEV por foto</h3>
          <ul className="space-y-1" aria-label="Entradas a KEV por foto mensual">
            {p.snapshots.map((s) => (
              <li key={s.snapshot} className="grid grid-cols-[84px_1fr_28px] items-center gap-2 text-[12px]">
                <span className="tabular-nums text-muted">{s.snapshot.slice(0, 7)}</span>
                <span className="h-2 rounded-sm bg-sunken" role="presentation"><span className={`block h-2 rounded-sm ${s.split === 'prueba' ? 'bg-ink' : s.split === 'validacion' ? 'bg-muted' : 'bg-accent'}`} style={{ width: `${(s.positives / maxPos) * 100}%` }} /></span>
                <span className="text-right tabular-nums">{s.positives}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 flex flex-wrap gap-3 text-[12px] text-muted">
            <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-accent" aria-hidden /> Desarrollo</span>
            <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-muted" aria-hidden /> Validación</span>
            <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-ink" aria-hidden /> Prueba</span>
          </p>
        </div>
      </div>
    </div>
  )
}

function Variables({ p }: { p: Profile }) {
  const [sel, setSel] = useState(p.numeric[0]?.name ?? '')
  const [cat, setCat] = useState(p.categorical[0]?.name ?? '')
  const row = p.numeric.find((r) => r.name === sel)
  const crow = p.categorical.find((r) => r.name === cat)
  const totPos = row ? Math.max(1, row.hist.reduce((a, b) => a + b.pos, 0)) : 1
  const totNeg = row ? Math.max(1, row.hist.reduce((a, b) => a + b.neg, 0)) : 1
  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-1 text-[13px] font-semibold">Variables numéricas: entraron a KEV frente al resto</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead><tr><th className={th}>Variable</th><th className={`${th} text-right`}>Sin dato</th><th className={`${th} text-right`}>Mediana KEV</th><th className={`${th} text-right`}>Mediana resto</th><th className={`${th} text-right`}>P75 KEV</th><th className={`${th} text-right`}>P75 resto</th><th className={`${th} text-right`}>Separa (AUC)</th></tr></thead>
            <tbody>
              {p.numeric.map((r) => (
                <tr key={r.name} title={r.description}>
                  <td className={`${td} font-mono text-[12px]`}>{r.name}</td>
                  <td className={`${td} text-right tabular-nums`}>{num(r.missing_pct, '%')}</td>
                  <td className={`${td} text-right tabular-nums`}>{smart(r.median_pos)}</td>
                  <td className={`${td} text-right tabular-nums`}>{smart(r.median_neg)}</td>
                  <td className={`${td} text-right tabular-nums`}>{smart(r.p75_pos)}</td>
                  <td className={`${td} text-right tabular-nums`}>{smart(r.p75_neg)}</td>
                  <td className={`${td} text-right font-medium tabular-nums`}>{num(r.auc, '', 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <How>{p.how_to_read.numeric}</How>
      </div>

      {row && row.hist.length > 0 && (
        <div>
          <div className="mb-2 flex flex-wrap items-end gap-3">
            <h3 className="text-[13px] font-semibold">Distribución por tramos</h3>
            <div className="w-56"><Select aria-label="Variable de la distribución" value={sel} onChange={(e) => setSel(e.target.value)}>
              {p.numeric.filter((r) => r.hist.length).map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
            </Select></div>
          </div>
          <ul className="space-y-1.5" aria-label={`Distribución de ${row.name}: porcentaje de cada grupo por tramo`}>
            {row.hist.map((b) => (
              <li key={b.label} className="grid grid-cols-[110px_1fr_1fr] items-center gap-2 text-[12px]">
                <span className="truncate tabular-nums text-muted">{b.label}</span>
                <span className="flex items-center gap-1.5"><span className="h-2 flex-1 rounded-sm bg-sunken" role="presentation"><span className="block h-2 rounded-sm bg-accent" style={{ width: `${(b.pos / totPos) * 100}%` }} /></span><span className="w-12 text-right tabular-nums">{num((100 * b.pos) / totPos, '%', 0)}</span></span>
                <span className="flex items-center gap-1.5"><span className="h-2 flex-1 rounded-sm bg-sunken" role="presentation"><span className="block h-2 rounded-sm bg-muted" style={{ width: `${(b.neg / totNeg) * 100}%` }} /></span><span className="w-12 text-right tabular-nums">{num((100 * b.neg) / totNeg, '%', 0)}</span></span>
              </li>
            ))}
          </ul>
          <p className="mt-1 flex gap-4 text-[12px] text-muted">
            <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-accent" aria-hidden /> Entraron a KEV</span>
            <span className="flex items-center gap-1.5"><span className="size-2 rounded-sm bg-muted" aria-hidden /> Resto</span>
          </p>
        </div>
      )}

      {crow && (
        <div>
          <div className="mb-2 flex flex-wrap items-end gap-3">
            <h3 className="text-[13px] font-semibold">Variables categóricas</h3>
            <div className="w-56"><Select aria-label="Variable categórica" value={cat} onChange={(e) => setCat(e.target.value)}>
              {p.categorical.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
            </Select></div>
            <span className="text-[12px] text-muted">{crow.cardinality} categorías · {crow.description}</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>Categoría</th><th className={`${th} text-right`}>Filas</th><th className={`${th} text-right`}>Entraron a KEV</th><th className={`${th} text-right`}>Proporción de KEV</th></tr></thead>
              <tbody>
                {crow.top.map((t) => (
                  <tr key={t.value}>
                    <td className={`${td} font-mono text-[12px]`}>{t.value}{t.small && <span className="ml-2 font-sans"><Meta>orientativo</Meta></span>}</td>
                    <td className={`${td} text-right tabular-nums`}>{int(t.rows)}</td>
                    <td className={`${td} text-right tabular-nums`}>{t.positives}</td>
                    <td className={`${td} text-right tabular-nums`}>{num(t.prevalence_pct, '%', 3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <How>{p.how_to_read.categorical}</How>
        </div>
      )}
    </div>
  )
}

const SAMPLE_COLS = ['snapshot', 'cve', 'label', 'epss', 'percentile', 'cvss', 'cna', 'cwe', 'ssvc_exploitation', 'edb_exploits', 'days_published', 'split'] as const
function Sample({ id }: { id: string }) {
  const [label, setLabel] = useState<'' | '0' | '1'>('1')
  const q = useQuery({ queryKey: ['ml-sample', id, label], queryFn: () => api.get<Record<string, unknown>[]>(`/ml/datasets/${id}/sample`, { limit: 50, ...(label ? { label } : {}) }) })
  return (
    <div>
      <div role="group" aria-label="Filas a mostrar" className="mb-2 flex gap-1">
        {([['1', 'Entraron a KEV'], ['0', 'Resto'], ['', 'Todas']] as const).map(([v, l]) => (
          <button key={v} type="button" aria-pressed={label === v} onClick={() => setLabel(v)}
            className={`h-7 rounded-full px-3 text-[12px] transition-colors duration-150 pointer-coarse:h-10 ${label === v ? 'bg-ink font-medium text-bg' : 'bg-sunken text-muted hover:text-ink'}`}>{l}</button>
        ))}
      </div>
      {q.isPending ? <Skeleton cols={6} rows={5} /> : q.isError ? <ErrorState message={q.error.message} /> : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full text-[12px]">
            <thead><tr>{SAMPLE_COLS.map((c) => <th key={c} className={th}>{c}</th>)}</tr></thead>
            <tbody>
              {q.data.map((r, i) => (
                <tr key={`${String(r.cve)}-${String(r.snapshot)}-${i}`}>
                  {SAMPLE_COLS.map((c) => <td key={c} className={`${td} whitespace-nowrap tabular-nums ${c === 'cve' ? 'font-mono' : ''}`}>{typeof r[c] === 'number' ? num(r[c] as number, '', c === 'epss' || c === 'percentile' ? 4 : 1) : String(r[c] ?? '—')}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-1 text-[12px] text-muted">Las primeras 50 filas; el archivo completo está en el volumen de datos del laboratorio.</p>
    </div>
  )
}

function Metadata({ d }: { d: Dataset }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: d.name, description: d.description, notes: d.notes, tags: d.tags.join(', ') })
  const save = useMutation({
    mutationFn: () => api.patch<Dataset>(`/ml/datasets/${d.id}`, { ...form, tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean) }),
    onSuccess: () => { toast.success('Metadata guardada'); void qc.invalidateQueries({ queryKey: ['ml-datasets'] }); void qc.invalidateQueries({ queryKey: ['ml-dataset', d.id] }) },
    onError: (e) => toast.error((e as Error).message),
  })
  const editable = can('ml', 'edit')
  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Nombre"><Input value={form.name} disabled={!editable} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Etiquetas (separadas por coma)"><Input value={form.tags} disabled={!editable} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></Field>
        <Field label="Descripción"><Textarea rows={3} value={form.description} disabled={!editable} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label="Notas"><Textarea rows={3} value={form.notes} disabled={!editable} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
      </div>
      {editable && <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending || form.name.trim().length < 3}>Guardar metadata</Button>}

      <div>
        <h3 className="mb-1 text-[13px] font-semibold">Parámetros de construcción</h3>
        <p className="text-[13px]">
          Fotos mensuales desde {formatDate(d.params.start)} ({d.params.snapshots} fotos) · horizonte de {d.params.horizon_days} días · KEV hasta {formatDate(d.params.until)} ·
          negativos muestreados al {num(d.params.neg_rate * 100, '%', 1)} · semilla {d.params.seed} · partición {d.params.split}.
        </p>
      </div>

      <div>
        <h3 className="mb-1 text-[13px] font-semibold">Fuentes y licencias</h3>
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-[12px]">
            <thead><tr><th className={th}>Fuente</th><th className={th}>Archivo</th><th className={`${th} text-right`}>Tamaño</th><th className={th}>SHA-256</th><th className={th}>Licencia</th></tr></thead>
            <tbody>
              {d.sources.map((s, i) => (
                <tr key={`${s.kind}-${s.file ?? i}`}>
                  <td className={`${td} whitespace-nowrap`}>{s.name}</td>
                  <td className={`${td} whitespace-nowrap font-mono`}>{s.file ?? s.url}{s.model_version ? ` · ${s.model_version}` : ''}</td>
                  <td className={`${td} text-right tabular-nums`}>{s.bytes ? `${num(s.bytes / 1_048_576, '', 1)} MB` : s.entries ? `${int(s.entries)} entradas` : '—'}</td>
                  <td className={`${td} font-mono`} title={s.sha256}>{s.sha256 ? `${s.sha256.slice(0, 12)}…` : '—'}</td>
                  <td className={td}>{s.license}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {d.excluded && d.excluded.length > 0 && (
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Variables descartadas por fuga de información</h3>
          <p className="mb-1 text-[12px] text-muted">Datos que existen hoy pero que no estaban disponibles (o no con ese valor) en la fecha de cada foto: usarlos inflaría las métricas.</p>
          <ul className="divide-y divide-line text-[13px]">
            {d.excluded.map((x) => <li key={x.name} className="py-1.5"><span className="font-medium">{x.name}</span> <span className="text-muted">({x.source})</span>: {x.reason}</li>)}
          </ul>
        </div>
      )}

      {d.features && (
        <div>
          <h3 className="mb-1 text-[13px] font-semibold">Diccionario de variables</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead><tr><th className={th}>Variable</th><th className={th}>Tipo</th><th className={th}>Fuente</th><th className={th}>Qué es</th></tr></thead>
              <tbody>
                {d.features.map((f) => (
                  <tr key={f.name}>
                    <td className={`${td} font-mono text-[12px]`}>{f.name}</td>
                    <td className={td}>{f.type === 'num' ? 'Numérica' : 'Categórica'}</td>
                    <td className={`${td} whitespace-nowrap`}>{f.source}</td>
                    <td className={td}>{f.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

export function DatasetDetail({ id }: { id: string }) {
  const [tab, setTab] = useState<Tab>('resumen')
  const d = useQuery({ queryKey: ['ml-dataset', id], queryFn: () => api.get<Dataset>(`/ml/datasets/${id}`) })
  const ready = d.data?.status === 'ready'
  const p = useQuery({ queryKey: ['ml-profile', id], queryFn: () => api.get<Profile>(`/ml/datasets/${id}/profile`), enabled: ready })
  if (d.isPending) return <Panel className="p-4"><Skeleton cols={3} rows={5} /></Panel>
  if (d.isError) return <Panel><ErrorState message={d.error.message} onRetry={() => void d.refetch()} /></Panel>
  const ds = d.data
  return (
    <Panel className="p-4">
      <div className="mb-3">
        <h2 className="text-[17px] font-semibold">{ds.name}</h2>
        <p className="text-[12px] text-muted">
          {ds.description || 'Sin descripción'}{ds.created_at && ` · creado ${formatLima(ds.created_at)}`}
          {ds.tags.length > 0 && <> · {ds.tags.map((t) => <span key={t} className="mr-1"><Meta>{t}</Meta></span>)}</>}
        </p>
      </div>
      {ds.status === 'failed' ? (
        <p className="text-[13px]">La construcción falló: {ds.stats.error ?? 'error desconocido'}.</p>
      ) : !ready ? (
        <p className="text-[13px] text-muted">El dataset se está construyendo…</p>
      ) : (
        <>
          <Tabs tabs={TABS} value={tab} onChange={setTab} label="Secciones del dataset" />
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
            {tab === 'metadata' ? <Metadata key={ds.updated_at ?? ds.id} d={ds} /> : tab === 'muestra' ? <Sample id={id} /> : p.isPending ? <Skeleton cols={3} rows={6} /> : p.isError ? <ErrorState message={p.error.message} onRetry={() => void p.refetch()} /> : (
              tab === 'resumen' ? <Summary p={p.data} /> : tab === 'validacion' ? (
                <div><CheckList checks={p.data.checks} /><How>{p.data.how_to_read.checks}</How></div>
              ) : <Variables p={p.data} />
            )}
          </div>
        </>
      )}
    </Panel>
  )
}

