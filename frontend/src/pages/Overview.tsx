import { EmptyState, PageHeader, Panel } from '../components/ui'
import { useAuth } from '../lib/auth'

export default function Overview() {
  const { user } = useAuth()
  return (
    <>
      <PageHeader title="Resumen" subtitle={`Sesión de ${user?.full_name} · ${user?.role}`} />
      <Panel>
        <EmptyState
          title="Aún no hay datos de exposición"
          hint="Los KPIs de CVEs en KEV, SLA y tendencia aparecen cuando se importen hallazgos y corra el primer cruce diario (fases 2 a 4)."
        />
      </Panel>
    </>
  )
}
