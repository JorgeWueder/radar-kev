import { Navigate, Route, Routes } from 'react-router-dom'

import { Shell } from './components/Shell'
import { useAuth } from './lib/auth'
import type { Action } from './lib/permissions'
import Audit from './pages/Audit'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Profile from './pages/Profile'
import Roles from './pages/Roles'
import Users from './pages/Users'

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
        <Route path="/usuarios" element={<Protected module="users"><Users /></Protected>} />
        <Route path="/roles" element={<Protected module="roles"><Roles /></Protected>} />
        <Route path="/bitacora" element={<Protected module="audit"><Audit /></Protected>} />
        <Route path="/perfil" element={<Protected><Profile /></Protected>} />
      </Route>
      <Route path="*" element={<Navigate to="/resumen" replace />} />
    </Routes>
  )
}
