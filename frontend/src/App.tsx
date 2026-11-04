import { Navigate, Route, Routes } from 'react-router-dom'

import { Shell } from './components/Shell'
import { useAuth } from './lib/auth'
import type { Action } from './lib/permissions'
import Alerts from './pages/Alerts'
import Assistant from './pages/Assistant'
import Assets from './pages/Assets'
import Audit from './pages/Audit'
import Imports from './pages/Imports'
import Kev from './pages/Kev'
import Runs from './pages/Runs'
import SettingsPage from './pages/Settings'
import TicketDetail from './pages/TicketDetail'
import Tickets from './pages/Tickets'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Profile from './pages/Profile'
import Roles from './pages/Roles'
import Users from './pages/Users'
import Vulnerabilities from './pages/Vulnerabilities'

function Protected({ module, action = 'view', children }: { module?: string; action?: Action; children: React.ReactNode }) {
  const { user, can } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  if (module && !can(module, action)) return <Navigate to="/resumen" replace />
  return <>{children}</>
}

export default function App() {
  const { user, loading } = useAuth()
  if (loading) return <div className="grid min-h-screen place-items-center text-muted" role="status">Cargando…</div>
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={user ? <Shell /> : <Navigate to="/login" replace />}>
        <Route path="/resumen" element={<Protected module="dashboard"><Overview /></Protected>} />
        <Route path="/asistente" element={<Protected module="ai"><Assistant /></Protected>} />
        <Route path="/alertas" element={<Protected module="alerts"><Alerts /></Protected>} />
        <Route path="/tickets" element={<Protected module="tickets"><Tickets /></Protected>} />
        <Route path="/tickets/:id" element={<Protected module="tickets"><TicketDetail /></Protected>} />
        <Route path="/activos" element={<Protected module="assets"><Assets /></Protected>} />
        <Route path="/importacion" element={<Protected module="imports"><Imports /></Protected>} />
        <Route path="/vulnerabilidades" element={<Protected module="vulnerabilities"><Vulnerabilities /></Protected>} />
        <Route path="/kev" element={<Protected module="kev"><Kev /></Protected>} />
        <Route path="/ejecuciones" element={<Protected module="workflow"><Runs /></Protected>} />
        <Route path="/configuracion" element={<Protected module="settings"><SettingsPage /></Protected>} />
        <Route path="/usuarios" element={<Protected module="users"><Users /></Protected>} />
        <Route path="/roles" element={<Protected module="roles"><Roles /></Protected>} />
        <Route path="/bitacora" element={<Protected module="audit"><Audit /></Protected>} />
        <Route path="/perfil" element={<Protected><Profile /></Protected>} />
      </Route>
      <Route path="*" element={<Navigate to="/resumen" replace />} />
    </Routes>
  )
}
