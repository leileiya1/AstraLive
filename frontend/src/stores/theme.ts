import { create } from 'zustand'
// Dark is the product default. The choice is a per-browser convenience only.
export type Theme = 'dark' | 'light'
const KEY = 'astralive.theme'
function read(): Theme {
  try { return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark' } catch { return 'dark' }
}
function apply(theme: Theme) {
  if (typeof document !== 'undefined') document.documentElement.dataset.theme = theme
}
const initial = typeof window === 'undefined' ? 'dark' : read()
apply(initial)
export const useTheme = create<{ theme: Theme; setTheme: (t: Theme) => void; toggle: () => void }>((set, get) => ({
  theme: initial,
  setTheme: (theme) => { apply(theme); try { localStorage.setItem(KEY, theme) } catch { /* storage unavailable */ } set({ theme }) },
  toggle: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
}))
