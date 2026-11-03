import { IconContext, Moon, Crosshair, Sun } from '@phosphor-icons/react'
import { useState } from 'react'
import { Toaster } from 'sonner'

import { applyTheme } from './lib/theme'

export default function App() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const next = !dark
    applyTheme(next ? 'dark' : 'light')
    setDark(next)
  }
  return (
    <IconContext.Provider value={{ weight: 'regular', size: 18 }}>
      <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-5 py-3">
        <div className="flex items-center gap-2 font-semibold">
          <Crosshair /> Radar KEV/EPSS
        </div>
        <button
          onClick={toggle}
          aria-label={dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
          className="rounded-md border border-[var(--border)] p-2 transition-transform duration-150 ease-[var(--ease-out-strong)] active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
        >
          {dark ? <Sun /> : <Moon />}
        </button>
      </header>
      <main className="p-5">
        <h1 className="text-xl font-semibold">Radar de explotación activa</h1>
        <p className="mt-1 text-[var(--muted)]">Fase 0: esqueleto de la aplicación.</p>
      </main>
      <Toaster position="bottom-right" />
    </IconContext.Provider>
  )
}
