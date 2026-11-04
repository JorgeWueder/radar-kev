import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { EmptyState, ErrorState, PageHeader, Panel, Skeleton, StatusBadge, td, th } from '../components/ui'
import { api } from '../lib/api'
import { formatDate, formatLima } from '../lib/format'
import { BAND, CRITICALITY, type Kind } from '../lib/labels'

interface Kpis {
  open_kev: number; new_kev_24h: number; new_kev_7d: number; sla_overdue: number; sla_due_soon: number; sla_overdue_kev: number
  active_total: number; by_band: Record<string, number>; kev_by_asset_criticality: Record<string, number>
  kev_epss_distribution: Record<string, number>; mttr_days: number | null; sla_compliance_pct: number | null; resolved_90d: number
  top_assets: { hostname: string; criticality: number; environment: string; kev_count: number; max_risk: number | null }[]
  top_risks: { cve_id: string; hostname: string; risk_score: number | null; band: string | null; sla_due_date: string | null }[]
  last_run: { status: string; started_at: string; new_matches: number; errors: number } | null
}
interface Point { date: string; kev_open: number; sla_overdue: number }

const RUN: Record<string, [Kind, string]> = { success: ['ok', 'Correcta'], partial: ['warn', 'Con avisos'], failed: ['danger', 'Fallida'], running: ['neutral', 'En curso'] }
const EPSS_LABEL: [string, string][] = [['mayor_90', '≥ 90 %'], ['50_a_90', '50 a 90 %'], ['10_a_50', '10 a 50 %'], ['menor_10', '< 10 %'], ['sin_dato', 'Sin dato']]

/** Cifra con etiqueta: el número es tipografía, no una tarjeta con adorno. */
function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'danger' | 'warn' }) {
  return (
    <div className="bg-surface px-4 py-3">
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className={`text-[28px] font-semibold leading-tight tabular-nums ${tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warn' : ''}`}>{value}</dd>
      {hint && <dd className="text-[12px] text-muted">{hint}</dd>}
    </div>
  )
}

function Bars({ rows, total }: { rows: [string, number][]; total: number }) {
  return (
    <ul className="space-y-2">
      {rows.map(([label, n]) => (
        <li key={label} className="grid grid-cols-[90px_1fr_32px] items-center gap-2 text-[13px]">
          <span className="text-muted">{label}</span>
          <span className="h-2 rounded-sm bg-sunken" role="presentation"><span className="block h-2 rounded-sm bg-accent" style={{ width: `${total ? (n / total) * 100 : 0}%` }} /></span>
          <span className="text-right tabular-nums">{n}</span>
        </li>
      ))}
    </ul>
  )
}

export default function Overview() {
  const k = useQuery({ queryKey: ['dash-kpis'], queryFn: () => api.get<Kpis>('/dashboard/kpis'), refetchInterval: 60_000 })
  const trend = useQuery({ queryKey: ['dash-trend'], queryFn: () => api.get<Point[]>('/dashboard/trend', { days: 60 }) })

  if (k.isPending) return <><PageHeader title="Resumen" /><Panel><Skeleton cols={4} rows={6} /></Panel></>
  if (k.isError) return <><PageHeader title="Resumen" /><Panel><ErrorState message={k.error.message} onRetry={() => void k.refetch()} /></Panel></>
  const d = k.data
  const empty = d.active_total === 0
  const run = d.last_run ? RUN[d.last_run.status] ?? (['neutral', d.last_run.status] as [Kind, string]) : null
  const critTotal = Object.values(d.kev_by_asset_criticality).reduce((a, b) => a + b, 0)
  const epssTotal = Object.values(d.kev_epss_distribution).reduce((a, b) => a + b, 0)

  return (
    <>
      <PageHeader
        title="Resumen de exposición"
        subtitle="¿Qué debo remediar primero? Vulnerabilidades con explotación activa confirmada (CISA KEV) presentes en su inventario."
        actions={run && d.last_run && (
          <Link to="/ejecuciones" className="flex items-center gap-2 text-[13px] text-muted hover:text-ink">
            Última ejecución <StatusBadge kind={run[0]}>{run[1]}</StatusBadge> <span className="font-mono text-[12px]">{formatLima(d.last_run.started_at)}</span>
          </Link>
        )}
      />
      {empty ? (
        <Panel>
          <EmptyState title="Aún no hay hallazgos abiertos" hint="Importe el reporte de un escáner y deje correr el cruce diario para ver aquí su exposición."
            action={<Link to="/importacion" className="text-[13px] font-medium text-accent underline underline-offset-2">Ir a Importación</Link>} />
        </Panel>
      ) : (
        <>
          <Panel className="mb-4 overflow-hidden">
            <dl className="grid grid-cols-2 gap-px bg-line md:grid-cols-3 xl:grid-cols-6">
              <Stat label="CVEs KEV en mi entorno" value={String(d.open_kev)} tone={d.open_kev > 0 ? 'danger' : undefined} hint={`de ${d.active_total} hallazgos abiertos`} />
              <Stat label="Nuevos en KEV" value={`${d.new_kev_24h} · ${d.new_kev_7d}`} hint="últimas 24 h · 7 días" />
              <Stat label="SLA vencidos" value={String(d.sla_overdue)} tone={d.sla_overdue > 0 ? 'danger' : undefined} hint={`${d.sla_overdue_kev} en KEV`} />
              <Stat label="SLA por vencer" value={String(d.sla_due_soon)} tone={d.sla_due_soon > 0 ? 'warn' : undefined} hint="próximos 7 días" />
              <Stat label="MTTR" value={d.mttr_days === null ? '—' : `${String(d.mttr_days).replace('.', ',')} d`} hint={`${d.resolved_90d} mitigados en 90 días`} />
              <Stat label="Cumplimiento de SLA" value={d.sla_compliance_pct === null ? '—' : `${String(d.sla_compliance_pct).replace('.', ',')} %`} hint="mitigados en plazo" />
            </dl>
          </Panel>

          <div className="mb-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
            <Panel className="p-4">
              <h2 className="text-[14px] font-semibold">Tendencia de exposición</h2>
              <p className="mb-2 text-[12px] text-muted">CVEs KEV abiertos y hallazgos con SLA vencido, últimos 60 días.</p>
              {trend.isPending ? <Skeleton cols={1} rows={4} /> : trend.isError ? <ErrorState message={trend.error.message} onRetry={() => void trend.refetch()} /> : trend.data.length < 2 ? (
                <p className="py-8 text-center text-[13px] text-muted">Se necesitan al menos dos días de datos para dibujar la tendencia.</p>
              ) : (
                <figure aria-label={`Tendencia: ${trend.data[0].kev_open} KEV abiertos al inicio y ${trend.data[trend.data.length - 1].kev_open} al final`}>
                  <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={trend.data} margin={{ top: 6, right: 12, bottom: 0, left: -18 }}>
                      <CartesianGrid stroke="var(--line)" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={(v: string) => formatDate(v).slice(0, 5)} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={{ stroke: 'var(--line)' }} minTickGap={28} />
                      <YAxis allowDecimals={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 6, fontSize: 12 }} labelFormatter={(v) => formatDate(String(v))} />
                      <Line type="monotone" dataKey="kev_open" name="KEV abiertos" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
                      <Line type="monotone" dataKey="sla_overdue" name="SLA vencidos" stroke="var(--danger)" strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                  <figcaption className="mt-1 flex gap-4 text-[12px] text-muted">
                    <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-accent" /> KEV abiertos</span>
                    <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t-2 border-dashed border-danger" /> SLA vencidos</span>
                  </figcaption>
                </figure>
              )}
            </Panel>
            <Panel className="p-4">
              <h2 className="mb-2 text-[14px] font-semibold">Principales riesgos</h2>
              <ul className="divide-y divide-line">
                {d.top_risks.map((r) => (
                  <li key={`${r.cve_id}${r.hostname}`} className="flex items-center justify-between gap-2 py-2 text-[13px]">
                    <span className="min-w-0"><span className="whitespace-nowrap font-mono text-[12px] font-medium">{r.cve_id}</span><span className="block truncate font-mono text-[12px] text-muted">{r.hostname}</span></span>
                    <span className="flex shrink-0 items-center gap-2">
                      {r.sla_due_date && <span className="text-[12px] tabular-nums text-muted">{formatDate(r.sla_due_date)}</span>}
                      {r.band && <StatusBadge kind={BAND[r.band][0]}>{r.risk_score?.toFixed(0)} · {BAND[r.band][1]}</StatusBadge>}
                    </span>
                  </li>
                ))}
              </ul>
              <Link to="/vulnerabilidades" className="mt-2 inline-block text-[13px] font-medium text-accent hover:underline">Ver todas las vulnerabilidades</Link>
            </Panel>
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr_1fr]">
            <Panel className="overflow-x-auto">
              <h2 className="px-4 pt-3 text-[14px] font-semibold">Activos más expuestos</h2>
              <table className="mt-1 w-full text-[13px]">
                <thead><tr><th className={th}>Activo</th><th className={th}>Criticidad</th><th className={`${th} text-right`}>KEV</th><th className={`${th} text-right`}>Riesgo máx.</th></tr></thead>
                <tbody>
                  {d.top_assets.map((a) => (
                    <tr key={a.hostname}>
                      <td className={`${td} font-mono text-[12px] font-medium`}><Link to={`/activos?q=${a.hostname}`} className="hover:underline">{a.hostname}</Link></td>
                      <td className={td}>{CRITICALITY[a.criticality]}</td>
                      <td className={`${td} text-right tabular-nums`}>{a.kev_count}</td>
                      <td className={`${td} text-right tabular-nums`}>{a.max_risk?.toFixed(1) ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
            <Panel className="p-4">
              <h2 className="mb-2 text-[14px] font-semibold">KEV por criticidad del activo</h2>
              <Bars total={critTotal} rows={[4, 3, 2, 1].map((c) => [CRITICALITY[c], d.kev_by_asset_criticality[String(c)] ?? 0] as [string, number])} />
            </Panel>
            <Panel className="p-4">
              <h2 className="mb-2 text-[14px] font-semibold">KEV por probabilidad EPSS</h2>
              <Bars total={epssTotal} rows={EPSS_LABEL.map(([k2, l]) => [l, d.kev_epss_distribution[k2] ?? 0] as [string, number])} />
            </Panel>
          </div>
        </>
      )}
    </>
  )
}
