export const CRITICALITY: Record<number, string> = { 1: 'Baja', 2: 'Media', 3: 'Alta', 4: 'Crítica' }

export const ENVIRONMENT: Record<string, string> = { prod: 'Producción', staging: 'Preproducción', dev: 'Desarrollo' }

export const ASSET_TYPE: Record<string, string> = {
  server: 'Servidor',
  workstation: 'Estación de trabajo',
  network: 'Red',
  database: 'Base de datos',
  application: 'Aplicación',
  cloud: 'Nube',
  other: 'Otro',
}

export const VULN_STATUS: Record<string, string> = {
  open: 'Abierta',
  in_progress: 'En remediación',
  mitigated: 'Mitigada',
  accepted: 'Riesgo aceptado',
  false_positive: 'Falso positivo',
}

/** Criticidad de negocio → tono del badge (siempre se muestra también el texto). */
export function criticalityKind(c: number): 'danger' | 'warn' | 'neutral' {
  return c >= 4 ? 'danger' : c === 3 ? 'warn' : 'neutral'
}

export type Kind = 'ok' | 'warn' | 'danger' | 'neutral'

export const BAND: Record<string, [Kind, string]> = {
  critical: ['danger', 'Crítico'],
  high: ['warn', 'Alto'],
  medium: ['neutral', 'Medio'],
  low: ['ok', 'Bajo'],
}

export const SLA: Record<string, [Kind, string]> = {
  vencido: ['danger', 'Vencido'],
  por_vencer: ['warn', 'Por vencer'],
  en_plazo: ['ok', 'En plazo'],
  no_aplica: ['neutral', 'No aplica'],
}

export const TICKET_STATUS: Record<string, [Kind, string]> = {
  open: ['warn', 'Abierto'],
  in_progress: ['neutral', 'En remediación'],
  resolved: ['ok', 'Resuelto'],
  closed: ['ok', 'Cerrado'],
  risk_accepted: ['neutral', 'Riesgo aceptado'],
}

export const PRIORITY: Record<string, [Kind, string]> = {
  critical: ['danger', 'Crítica'],
  high: ['warn', 'Alta'],
  medium: ['neutral', 'Media'],
  low: ['ok', 'Baja'],
}
