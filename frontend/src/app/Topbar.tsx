import { useQuery } from '@tanstack/react-query'
import { Menu, Moon, Sun } from 'lucide-react'
import { api } from '../api/client'
import { StatusDot } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { lookSession } from '../lib/status'
import { cn } from '../lib/utils'
import { useTheme } from '../stores/theme'
import { useUi } from '../stores/ui'

export function Topbar({ title, sessionId, roomName, onMenu, onOpenConsole }: { title: string; sessionId: string | null; roomName?: string; onMenu: () => void; onOpenConsole: () => void }) {
  const { theme, toggle } = useTheme()
  const mirrored = useUi(s => s.liveStatus)
  const session = useQuery({ queryKey: ['session', sessionId], queryFn: () => api.session(sessionId!), enabled: !!sessionId, refetchInterval: 10000 })
  const status = sessionId ? (mirrored?.sessionId === sessionId ? mirrored.status : session.data?.status) ?? null : null
  const look = lookSession(status)
  const live = status === 'LIVE' || status === 'DEGRADED'
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-border bg-bg/70 px-3 backdrop-blur-xl sm:gap-3 sm:px-6">
      <Button variant="ghost" size="icon" className="md:hidden" aria-label="打开导航" onClick={onMenu}><Menu className="size-5" /></Button>
      <p className="flex min-w-0 items-center gap-2 text-body"><span className="hidden text-fg-subtle sm:inline">AstraLive</span><span className="hidden text-fg-subtle sm:inline">/</span><span className="truncate font-medium text-fg">{title}</span></p>
      <div className="ml-auto flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={onOpenConsole}
          title={status ?? undefined}
          className={cn(
            'flex min-w-0 items-center gap-2 rounded-full border px-3 py-1.5 text-caption font-medium transition-colors',
            live ? 'border-live/35 bg-live-soft text-live hover:bg-live/20' : 'border-border bg-surface-2 text-fg-muted hover:text-fg',
          )}
        >
          <StatusDot tone={sessionId ? look.tone : 'neutral'} pulse={look.pulse} ping={look.ping} />
          <span className="shrink-0">{sessionId ? look.label : '未开播'}</span>
          {roomName && <span className="hidden max-w-40 truncate border-l border-current/20 pl-2 font-normal opacity-80 sm:inline">{roomName}</span>}
        </button>
        <Button variant="ghost" size="icon" aria-label={theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'} onClick={toggle}>
          {theme === 'dark' ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
        </Button>
      </div>
    </header>
  )
}
