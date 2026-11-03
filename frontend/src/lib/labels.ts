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
