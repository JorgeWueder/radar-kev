// Paneles de detalle (DetailDrawer) de las listas: CVE, activo, entrada KEV y ticket. Solo leen la API existente.
import { Skull, Target } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../lib/api'
import { dueText, daysUntil, formatDate, formatPct, slaProgress } from '../lib/format'
import { ASSET_TYPE, BAND, CRITICALITY, ENVIRONMENT, PRIORITY, SLA, TICKET_STATUS, VULN_STATUS } from '../lib/labels'
import type { Asset, KevRow, TicketRow, Vuln } from '../lib/types'
import { DetailDrawer, DrawerRow, Meta } from './kit'
import { Skeleton, StatusBadge } from './ui'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <h3 className="mb-1 text-[13px] font-semibold">{title}</h3>
      {children}
    </section>
  )
}

/** Barra de progreso del SLA: tiempo transcurrido entre la creación y el plazo. Gris; solo se pone roja si está vencido. */
export function SlaBar({ created, due, state }: { created: string; due: string | null; state: string }) {
  const [now] = useState(() => Date.now())
  if (!due || state === 'no_aplica') return <span className="text-[12px] text-muted">Sin plazo</span>
  const pct = slaProgress(created, due, now)
  const late = state === 'vencido'
  const left = daysUntil(due)
  return (
    <div className="min-w-[110px]">
      <div className="h-1.5 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-label="Avance del plazo de SLA" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct * 100)}>
        <div className={`h-full rounded-full ${late ? 'bg-danger' : 'bg-muted'}`} style={{ width: `${pct * 100}%` }} />
      </div>
      <p className={`mt-0.5 text-[12px] tabular-nums ${late ? 'font-medium text-danger' : 'text-muted'}`}>{left === null ? '' : dueText(left)}</p>
    </div>
  )
}

function useAffected(cve: string, enabled: boolean) {
  return useQuery({
    queryKey: ['affected', cve],
    queryFn: () => api.get<{ items: Vuln[] }>('/vulnerabilities', { q: cve, limit: 100 }),
    enabled,
    select: (r) => r.items.filter((v) => v.cve_id === cve),
  })
}

function AffectedList({ items, loading }: { items?: Vuln[]; loading: boolean }) {
  if (loading) return <Skeleton cols={2} rows={2} />
  if (!items || items.length === 0) return <p className="text-[13px] text-muted">Ningún activo de su inventario.</p>
  return (
    <ul className="divide-y divide-line rounded-lg border border-line">
      {items.map((v) => (
        <li key={v.id} className="flex items-center justify-between gap-2 px-3 py-2 text-[13px]">
          <span className="min-w-0">
            <Link to={`/activos?q=${v.asset.hostname}`} className="font-mono text-[12px] font-medium hover:underline">{v.asset.hostname}</Link>
            <span className="block text-[12px] text-muted">{ENVIRONMENT[v.asset.environment]} · {CRITICALITY[v.asset.criticality]}</span>
          </span>
          <Meta alert={v.sla_state === 'vencido'}>{SLA[v.sla_state][1]}</Meta>
        </li>
      ))}
    </ul>
  )
}

export function VulnDrawer({ v, onClose }: { v: Vuln | null; onClose: () => void }) {
  const open = v !== null
  const affected = useAffected(v?.cve_id ?? '', open)
  const ticket = useQuery({
    queryKey: ['ticket-for', v?.cve_id, v?.asset.hostname],
    queryFn: () => api.get<{ items: TicketRow[] }>('/tickets', { q: v?.cve_id, limit: 50 }),
    enabled: open,
    select: (r) => r.items.find((t) => t.cve_id === v?.cve_id && t.hostname === v?.asset.hostname) ?? null,
  })
  return (
    <DetailDrawer open={open} onClose={onClose} title={v?.cve_id ?? ''} subtitle={v ? `${v.asset.hostname} · ${ENVIRONMENT[v.asset.environment]}` : undefined}>
      {v && (
        <>
          <Section title="Riesgo">
            <dl>
              <DrawerRow label="Puntaje">
                {v.risk_score === null || !v.risk_band ? '—' : <span className="inline-flex items-center gap-2"><span className="font-semibold tabular-nums">{v.risk_score.toFixed(1)}</span><StatusBadge kind={BAND[v.risk_band][0]}>{BAND[v.risk_band][1]}</StatusBadge></span>}
              </DrawerRow>
              <DrawerRow label="SLA"><Meta alert={v.sla_state === 'vencido'}>{SLA[v.sla_state][1]}</Meta>{v.sla_due_date && v.sla_state !== 'no_aplica' && <span className="ml-2 tabular-nums text-muted">{formatDate(v.sla_due_date)}</span>}</DrawerRow>
              <DrawerRow label="Estado">{VULN_STATUS[v.status]}</DrawerRow>
            </dl>
          </Section>
          <Section title="Explotación">
            <dl>
              <DrawerRow label="CISA KEV">{v.in_kev ? <Meta icon={Target}>En el catálogo{v.kev_due_date ? ` · vence ${formatDate(v.kev_due_date)}` : ''}</Meta> : <span className="text-muted">No está en el catálogo</span>}</DrawerRow>
              <DrawerRow label="Ransomware">{v.ransomware ? <Meta icon={Skull}>Uso conocido</Meta> : <span className="text-muted">Sin uso conocido</span>}</DrawerRow>
              <DrawerRow label="EPSS">{formatPct(v.epss)}{v.percentile !== null && <span className="text-muted"> · percentil {formatPct(v.percentile, 0)}</span>}</DrawerRow>
              <DrawerRow label="CVSS">{v.cvss_score ?? '—'}</DrawerRow>
            </dl>
          </Section>
          <Section title="Activos afectados">
            <AffectedList items={affected.data} loading={affected.isPending} />
          </Section>
          <Section title="Ticket">
            {ticket.isPending ? <Skeleton cols={2} rows={1} /> : ticket.data ? (
              <p className="text-[13px]">
                <Link to={`/tickets/${ticket.data.id}`} className="font-mono text-[12px] font-medium text-link hover:underline">{ticket.data.code}</Link>
                <span className="text-muted"> · {TICKET_STATUS[ticket.data.status][1]} · {ticket.data.assignee?.name ?? 'sin asignar'}</span>
              </p>
            ) : <p className="text-[13px] text-muted">Sin ticket para este hallazgo.</p>}
          </Section>
        </>
      )}
    </DetailDrawer>
  )
}

export function AssetDrawer({ a, onClose }: { a: Asset | null; onClose: () => void }) {
  const open = a !== null
  const vulns = useQuery({
    queryKey: ['asset-vulns', a?.id],
    queryFn: () => api.get<{ items: Vuln[] }>('/vulnerabilities', { asset_id: a?.id, limit: 100 }),
    enabled: open,
  })
  return (
    <DetailDrawer open={open} onClose={onClose} title={a?.hostname ?? ''} subtitle={a ? `${ASSET_TYPE[a.asset_type]} · ${ENVIRONMENT[a.environment]}` : undefined}>
      {a && (
        <>
          <Section title="Datos del activo">
            <dl>
              <DrawerRow label="IP"><span className="font-mono text-[12px]">{a.ip ?? '—'}</span></DrawerRow>
              <DrawerRow label="Sistema operativo">{a.os ?? '—'}</DrawerRow>
              <DrawerRow label="Responsable">{a.owner_name ?? 'Sin asignar'}</DrawerRow>
              <DrawerRow label="Criticidad">{CRITICALITY[a.criticality]}</DrawerRow>
              <DrawerRow label="Estado">{a.is_active ? 'Activo' : 'Inactivo'}{a.auto_created && <span className="text-muted"> · creado por una importación, por completar</span>}</DrawerRow>
            </dl>
          </Section>
          <Section title={`CVEs del activo${vulns.data ? ` (${vulns.data.items.length})` : ''}`}>
            {vulns.isPending ? <Skeleton cols={2} rows={3} /> : vulns.data && vulns.data.items.length > 0 ? (
              <ul className="divide-y divide-line rounded-lg border border-line">
                {vulns.data.items.map((v) => (
                  <li key={v.id} className="flex items-center justify-between gap-2 px-3 py-2 text-[13px]">
                    <span className="min-w-0">
                      <span className="font-mono text-[12px] font-medium">{v.cve_id}</span>
                      <span className="block text-[12px] text-muted">{v.in_kev ? 'En KEV' : 'Fuera de KEV'} · {VULN_STATUS[v.status]}</span>
                    </span>
                    {v.risk_band && v.risk_score !== null && <StatusBadge kind={BAND[v.risk_band][0]}>{v.risk_score.toFixed(0)} · {BAND[v.risk_band][1]}</StatusBadge>}
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-muted">Este activo no tiene hallazgos registrados.</p>}
            <Link to="/vulnerabilidades" className="mt-2 inline-block text-[13px] font-medium text-link hover:underline">Ver todas las vulnerabilidades</Link>
          </Section>
        </>
      )}
    </DetailDrawer>
  )
}

export function KevDrawer({ k, onClose }: { k: KevRow | null; onClose: () => void }) {
  const open = k !== null
  const affected = useAffected(k?.cve_id ?? '', open && (k?.assets_affected ?? 0) > 0)
  return (
    <DetailDrawer open={open} onClose={onClose} title={k?.cve_id ?? ''} subtitle={k ? `${k.vendor_project} · ${k.product}` : undefined}>
      {k && (
        <>
          <Section title="Vulnerabilidad">
            <p className="text-[13px] font-medium">{k.vulnerability_name}</p>
            <p className="mt-1 text-[13px]">{k.short_description}</p>
          </Section>
          <Section title="Acción requerida (CISA)">
            <p className="text-[13px]">{k.required_action}</p>
          </Section>
          <Section title="Datos">
            <dl>
              <DrawerRow label="Agregada al catálogo">{formatDate(k.date_added)}</DrawerRow>
              <DrawerRow label="Fecha límite (CISA)">{formatDate(k.due_date)}</DrawerRow>
              <DrawerRow label="Ransomware">{k.ransomware_use === 'Known' ? <Meta icon={Skull}>Uso conocido</Meta> : <span className="text-muted">Sin uso conocido</span>}</DrawerRow>
              <DrawerRow label="EPSS">{formatPct(k.epss)}{k.percentile !== null && <span className="text-muted"> · percentil {formatPct(k.percentile, 0)}</span>}</DrawerRow>
              {k.cwes.length > 0 && <DrawerRow label="CWE"><span className="font-mono text-[12px]">{k.cwes.join(', ')}</span></DrawerRow>}
              {k.notes && <DrawerRow label="Notas"><span className="break-words text-[12px]">{k.notes}</span></DrawerRow>}
            </dl>
          </Section>
          <Section title="En mi entorno">
            {k.assets_affected === 0 ? <p className="text-[13px] text-muted">No afecta a ningún activo de su inventario.</p> : <AffectedList items={affected.data} loading={affected.isPending} />}
          </Section>
        </>
      )}
    </DetailDrawer>
  )
}

export function TicketDrawer({ t, onClose }: { t: TicketRow | null; onClose: () => void }) {
  return (
    <DetailDrawer open={t !== null} onClose={onClose} title={t?.code ?? ''} subtitle={t ? `${t.cve_id} en ${t.hostname}` : undefined}>
      {t && (
        <>
          <Section title="Ticket">
            <p className="text-[13px]">{t.title}</p>
            <dl className="mt-2">
              <DrawerRow label="Prioridad"><StatusBadge kind={PRIORITY[t.priority][0]}>{PRIORITY[t.priority][1]}</StatusBadge></DrawerRow>
              <DrawerRow label="Estado">{TICKET_STATUS[t.status][1]}</DrawerRow>
              <DrawerRow label="Responsable">{t.assignee?.name ?? 'Sin asignar'}</DrawerRow>
              <DrawerRow label="Plazo (SLA)"><SlaBar created={t.created_at} due={t.due_date} state={t.sla_state} /></DrawerRow>
            </dl>
          </Section>
          <Link to={`/tickets/${t.id}`} className="inline-flex h-8 items-center rounded-full bg-accent px-4 text-[13px] font-medium text-accent-ink hover:brightness-110 pointer-coarse:h-11">
            Abrir ticket completo
          </Link>
        </>
      )}
    </DetailDrawer>
  )
}
