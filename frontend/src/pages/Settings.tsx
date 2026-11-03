import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button, ErrorState, Field, Input, PageHeader, Panel, Skeleton, StatusBadge } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { formatLima } from '../lib/format'
import { BAND } from '../lib/labels'

interface Params {
  w_epss: number; w_percentile: number; w_cvss: number; w_asset: number; kev_floor: number; ransomware_bonus: number
  band_critical: number; band_high: number; band_medium: number
  sla_critical: number; sla_high: number; sla_medium: number; sla_low: number; due_soon_days: number
}
interface Scoring { version: number; created_at: string; params: Params; formula: string }
interface Preview { base: number; score: number; band: string; sla_days_from_detection: number }
interface Sample { in_kev: boolean; epss: number; percentile: number; cvss: number; criticality: number; ransomware: boolean }

const WEIGHTS: [keyof Params, string][] = [
  ['w_epss', 'EPSS (probabilidad)'], ['w_percentile', 'EPSS (percentil)'], ['w_cvss', 'CVSS'], ['w_asset', 'Criticidad del activo'],
]
const BANDS: [keyof Params, string][] = [['band_critical', 'Crítico desde'], ['band_high', 'Alto desde'], ['band_medium', 'Medio desde']]
const SLAS: [keyof Params, string][] = [
  ['sla_critical', 'Crítico (días)'], ['sla_high', 'Alto (días)'], ['sla_medium', 'Medio (días)'], ['sla_low', 'Bajo (días)'], ['due_soon_days', '"Por vencer" desde (días)'],
]

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export default function SettingsPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const cur = useQuery({ queryKey: ['scoring'], queryFn: () => api.get<Scoring>('/settings/scoring') })
  const [draft, setDraft] = useState<Params | null>(null)
  const [sample, setSample] = useState<Sample>({ in_kev: true, epss: 0.5, percentile: 0.9, cvss: 7.5, criticality: 3, ransomware: false })

  const params = draft ?? cur.data?.params ?? null
  const editable = can('settings', 'edit')
  const sum = params ? params.w_epss + params.w_percentile + params.w_cvss + params.w_asset : 0
  const sumOk = Math.abs(sum - 1) <= 0.001
  const bandsOk = params ? params.band_critical > params.band_high && params.band_high > params.band_medium : true
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(cur.data?.params)

  const setNum = (k: keyof Params, raw: string) => {
    if (!params) return
    const n = raw === '' ? 0 : Number(raw)
    if (Number.isNaN(n)) return
    setDraft({ ...params, [k]: n })
  }

  const dParams = useDebounced(params)
  const dSample = useDebounced(sample)
  const preview = useQuery({
    queryKey: ['scoring-preview', dParams, dSample],
    queryFn: () => api.post<Preview>('/settings/scoring/preview', { params: dParams, sample: dSample }),
    enabled: Boolean(dParams) && sumOk && bandsOk,
    retry: false,
  })

  const save = useMutation({
    mutationFn: () => api.put<Scoring>('/settings/scoring', draft),
    onSuccess: (s) => {
      toast.success(`Fórmula guardada como versión ${s.version}; se recalculó todo el inventario`)
      setDraft(null)
      void qc.invalidateQueries()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  if (cur.isPending) return <Panel><Skeleton cols={3} rows={8} /></Panel>
  if (cur.isError) return <Panel><ErrorState message={cur.error.message} onRetry={() => void cur.refetch()} /></Panel>
  if (!params) return null

  const num = (k: keyof Params, label: string, step = 1) => (
    <Field label={label} key={k}>
      <Input type="number" step={step} value={params[k]} disabled={!editable} onChange={(e) => setNum(k, e.target.value)} className="tabular-nums" />
    </Field>
  )
  const sampleNum = (k: 'epss' | 'percentile' | 'cvss', label: string, max: number, step: number) => (
    <Field label={label}><Input type="number" min={0} max={max} step={step} value={sample[k]} onChange={(e) => setSample({ ...sample, [k]: Number(e.target.value) })} className="tabular-nums" /></Field>
  )

  return (
    <>
      <PageHeader
        title="Configuración del score de riesgo"
        subtitle={`Versión activa ${cur.data.version} · guardada ${formatLima(cur.data.created_at)}. Cada cambio crea una versión nueva y recalcula el inventario.`}
        actions={editable && (
          <>
            {dirty && <Button onClick={() => setDraft(null)}>Descartar cambios</Button>}
            <Button variant="primary" disabled={!dirty || !sumOk || !bandsOk || save.isPending} onClick={() => save.mutate()}>Guardar nueva versión</Button>
          </>
        )}
      />
      <Panel className="mb-4 p-4">
        <h2 className="mb-2 text-[14px] font-semibold">Fórmula</h2>
        <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-muted">{cur.data.formula}</pre>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <Panel className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[14px] font-semibold">Pesos (deben sumar 1)</h2>
              <StatusBadge kind={sumOk ? 'ok' : 'danger'}>Suma {sum.toFixed(2)}{sumOk ? '' : ': ajuste los pesos'}</StatusBadge>
            </div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{WEIGHTS.map(([k, l]) => num(k, l, 0.05))}</div>
          </Panel>
          <Panel className="p-4">
            <h2 className="mb-3 text-[14px] font-semibold">Presencia en KEV</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {num('kev_floor', 'Piso del score en KEV')}{num('ransomware_bonus', 'Bono por ransomware')}
            </div>
            <p className="mt-2 text-[12px] text-muted">Todo CVE en KEV puntúa desde el piso; todo CVE fuera de KEV queda por debajo de él.</p>
          </Panel>
          <Panel className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[14px] font-semibold">Bandas y SLA</h2>
              {!bandsOk && <StatusBadge kind="danger">Debe cumplirse crítico &gt; alto &gt; medio</StatusBadge>}
            </div>
            <div className="grid grid-cols-3 gap-3">{BANDS.map(([k, l]) => num(k, l))}</div>
            <p className="mb-2 mt-4 text-[12px] text-muted">En KEV el SLA usa la fecha límite de CISA (dueDate). Fuera de KEV, estos días desde la detección:</p>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{SLAS.map(([k, l]) => num(k, l))}</div>
          </Panel>
        </div>
        <Panel className="h-fit p-4">
          <h2 className="mb-3 text-[14px] font-semibold">Simulador</h2>
          <div className="grid grid-cols-2 gap-3">
            {sampleNum('epss', 'EPSS (0 a 1)', 1, 0.05)}{sampleNum('percentile', 'Percentil (0 a 1)', 1, 0.05)}
            {sampleNum('cvss', 'CVSS (0 a 10)', 10, 0.1)}
            <Field label="Criticidad">
              <select className="h-8 w-full rounded-md border border-line bg-surface px-2 text-[13px]" value={sample.criticality} onChange={(e) => setSample({ ...sample, criticality: Number(e.target.value) })}>
                {[4, 3, 2, 1].map((c) => <option key={c} value={c}>{['', 'Baja', 'Media', 'Alta', 'Crítica'][c]}</option>)}
              </select>
            </Field>
          </div>
          <div className="mt-3 space-y-1 text-[13px]">
            <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={sample.in_kev} onChange={(e) => setSample({ ...sample, in_kev: e.target.checked })} /> Está en KEV</label>
            <label className="flex items-center gap-1.5"><input type="checkbox" className="accent-[var(--accent)]" checked={sample.ransomware} onChange={(e) => setSample({ ...sample, ransomware: e.target.checked })} /> Uso conocido en ransomware</label>
          </div>
          <div className="mt-4 rounded-md border border-line p-3" aria-live="polite">
            {preview.data ? (
              <>
                <div className="flex items-baseline justify-between">
                  <span className="text-[12px] text-muted">Score de riesgo</span>
                  <StatusBadge kind={BAND[preview.data.band][0]}>{BAND[preview.data.band][1]}</StatusBadge>
                </div>
                <p className="text-[28px] font-semibold leading-tight tabular-nums">{preview.data.score.toFixed(1)}</p>
                <p className="text-[12px] text-muted">Base {preview.data.base.toFixed(3)}{!sample.in_kev && ` · SLA de ${preview.data.sla_days_from_detection} días`}</p>
              </>
            ) : <p className="text-[13px] text-muted">{sumOk && bandsOk ? 'Calculando…' : 'Corrija los valores para simular.'}</p>}
          </div>
        </Panel>
      </div>
      <IntegrationsPanel />
    </>
  )
}

type Integrations = Record<'smtp_host' | 'smtp_port' | 'smtp_user' | 'smtp_password' | 'smtp_from' | 'alert_email_to' | 'webhook_url' | 'webhook_kind' | 'telegram_chat_id', string>

const KINDS: [string, string][] = [['generic', 'Genérico (Teams u otro)'], ['slack', 'Slack'], ['telegram', 'Telegram']]

function IntegrationsPanel() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const editable = can('settings', 'edit')
  const cur = useQuery({ queryKey: ['integrations'], queryFn: () => api.get<Integrations>('/settings/integrations') })
  const [draft, setDraft] = useState<Integrations | null>(null)
  const v = draft ?? cur.data
  const set = (k: keyof Integrations) => (e: { target: { value: string } }) => v && setDraft({ ...v, [k]: e.target.value })

  const save = useMutation({
    mutationFn: () => api.put<Integrations>('/settings/integrations', { ...draft, smtp_port: Number(draft?.smtp_port) }),
    onSuccess: () => { toast.success('Integraciones guardadas'); setDraft(null); void qc.invalidateQueries({ queryKey: ['integrations'] }) },
    onError: (e: Error) => toast.error(e.message),
  })
  const test = useMutation({
    mutationFn: (channel: 'email' | 'webhook') => api.post(`/settings/integrations/test-${channel}`),
    onSuccess: () => toast.success('Prueba enviada'),
    onError: (e: Error) => toast.error(e.message),
  })

  if (cur.isPending) return <Panel className="mt-4"><Skeleton cols={3} rows={4} /></Panel>
  if (cur.isError || !v) return <Panel className="mt-4"><ErrorState message={cur.error?.message ?? 'Error'} onRetry={() => void cur.refetch()} /></Panel>
  const f = (k: keyof Integrations, label: string, type = 'text', ph = '') => (
    <Field label={label}><Input type={type} placeholder={ph} value={v[k]} disabled={!editable} autoComplete="off" onChange={set(k)} /></Field>
  )
  return (
    <Panel className="mt-4 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-[14px] font-semibold">Canales de alerta</h2>
          <p className="text-[12px] text-muted">Alerta urgente por correo (SMTP) y por webhook. Los secretos se guardan cifrados y nunca se muestran.</p>
        </div>
        {editable && (
          <div className="flex gap-2">
            <Button disabled={draft !== null || test.isPending} onClick={() => test.mutate('email')}>Probar correo</Button>
            <Button disabled={draft !== null || test.isPending} onClick={() => test.mutate('webhook')}>Probar webhook</Button>
            <Button variant="primary" disabled={!draft || save.isPending} onClick={() => save.mutate()}>Guardar</Button>
          </div>
        )}
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {f('smtp_host', 'Servidor SMTP')}{f('smtp_port', 'Puerto', 'number')}{f('smtp_user', 'Usuario SMTP')}{f('smtp_password', 'Contraseña SMTP', 'password', 'Sin cambios')}
        {f('smtp_from', 'Remitente')}<div className="md:col-span-1 xl:col-span-3">{f('alert_email_to', 'Destinatarios (separados por coma)')}</div>
        <Field label="Tipo de webhook">
          <select className="h-8 w-full rounded-md border border-line bg-surface px-2 text-[13px]" value={v.webhook_kind} disabled={!editable} onChange={set('webhook_kind')}>
            {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <div className="md:col-span-1 xl:col-span-2">{f('webhook_url', 'URL del webhook', 'password', 'https://…')}</div>
        {v.webhook_kind === 'telegram' && f('telegram_chat_id', 'Chat ID de Telegram')}
      </div>
    </Panel>
  )
}
