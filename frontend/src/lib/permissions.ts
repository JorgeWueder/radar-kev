export type Action = 'view' | 'create' | 'edit' | 'delete' | 'export'

export function hasPermission(permissions: readonly string[], module: string, action: Action): boolean {
  return permissions.includes(`${module}:${action}`)
}

export const MODULE_LABELS: Record<string, string> = {
  dashboard: 'Dashboard',
  assets: 'Activos',
  imports: 'Importación',
  vulnerabilities: 'Vulnerabilidades',
  kev: 'Catálogo KEV',
  tickets: 'Tickets',
  alerts: 'Alertas',
  workflow: 'Ejecuciones',
  reports: 'Reportes',
  ai: 'Asistente IA',
  settings: 'Configuración',
  users: 'Usuarios',
  roles: 'Roles',
  audit: 'Bitácora',
  auth: 'Autenticación',
  app: 'Aplicación',
}

export const ACTION_LABELS: Record<string, string> = {
  view: 'Ver',
  create: 'Crear',
  edit: 'Editar',
  delete: 'Eliminar',
  export: 'Exportar',
}

export function moduleLabel(module: string): string {
  return MODULE_LABELS[module] ?? module
}
