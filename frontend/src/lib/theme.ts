export type Theme = 'light' | 'dark'

export function resolveTheme(stored: string | null, prefersDark: boolean): Theme {
  if (stored === 'light' || stored === 'dark') return stored
  return prefersDark ? 'dark' : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  try {
    localStorage.setItem('theme', theme)
  } catch {
    // almacenamiento no disponible: el tema solo vale para esta sesión
  }
}
