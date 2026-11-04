// Formas de las filas que comparten las listas y sus paneles de detalle (solo tipos de la API existente).
export interface Vuln {
  id: string; cve_id: string; cvss_score: number | null; status: string; last_seen: string
  asset: { id: string; hostname: string; ip: string | null; criticality: number; environment: string }
  risk_score: number | null; risk_band: string | null; sla_due_date: string | null; kev_matched_at: string | null
  in_kev: boolean; kev_due_date: string | null; ransomware: boolean; epss: number | null; percentile: number | null; sla_state: string
}

export interface Asset {
  id: string; hostname: string; ip: string | null; asset_type: string; os: string | null
  owner_id: string | null; owner_name: string | null; criticality: number; environment: string
  is_active: boolean; auto_created: boolean
}

export interface KevRow {
  cve_id: string; vendor_project: string; product: string; vulnerability_name: string; date_added: string
  due_date: string; ransomware_use: string; short_description: string; required_action: string; notes: string
  cwes: string[]; assets_affected: number; epss: number | null; percentile: number | null
}

export interface TicketRow {
  id: string; code: string; title: string; status: string; priority: string; assignee: { id: string; name: string } | null
  due_date: string | null; sla_state: string; cve_id: string; hostname: string; created_at: string; ai_generated: boolean
}
