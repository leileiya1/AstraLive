import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence } from 'motion/react'
import * as m from 'motion/react-m'
import { AudioLines, Boxes, ChevronsLeft, ChevronsRight, LayoutDashboard, MonitorPlay, Radio, Settings2, Sparkles, UserRound, X } from 'lucide-react'
import { Tooltip } from '../components/ui/tooltip'
import { cn } from '../lib/utils'

export type Page = 'dashboard' | 'avatars' | 'voices' | 'products' | 'rooms' | 'console' | 'settings'
const groups = [
  { title: '概览', items: [['dashboard', '总览', LayoutDashboard]] },
  { title: '直播', items: [['console', '直播控制台', MonitorPlay], ['rooms', '直播间', Radio]] },
  { title: '素材', items: [['avatars', '数字人', UserRound], ['voices', '音色', AudioLines], ['products', '商品', Boxes]] },
  { title: '系统', items: [['settings', '配置中心', Settings2]] },
] as const
export const pageTitles: Record<Page, string> = Object.fromEntries(groups.flatMap(g => g.items.map(([id, label]) => [id, label]))) as Record<Page, string>

function Brand({ compact }: { compact: boolean }) {
  return (
    <div className={cn('flex h-16 items-center gap-2.5 px-4', compact && 'justify-center px-0')}>
      <span className="grid size-8 shrink-0 place-items-center rounded-md bg-brand-gradient text-brand-fg shadow-glow"><Sparkles className="size-4" /></span>
      {!compact && <span className="flex flex-col leading-tight"><span className="font-semibold tracking-tight text-fg">AstraLive</span><span className="text-[11px] text-fg-subtle">AI 数字人直播控制台</span></span>}
    </div>
  )
}

function NavList({ page, onNavigate, compact, layoutId }: { page: Page; onNavigate: (p: Page) => void; compact: boolean; layoutId: string }) {
  return (
    <nav aria-label="主导航" className="flex flex-col gap-5 px-3 py-2">
      {groups.map(group => (
        <div key={group.title}>
          {compact ? <div className="mx-auto mb-2 h-px w-6 bg-border" /> : <p className="mb-1.5 px-3 text-[11px] font-medium tracking-wider text-fg-subtle">{group.title}</p>}
          <div className="flex flex-col gap-0.5">
            {group.items.map(([id, label, Icon]) => {
              const active = page === id
              return (
                <Tooltip key={id} content={label} disabled={!compact}>
                  <button
                    type="button"
                    onClick={() => onNavigate(id)}
                    aria-current={active ? 'page' : undefined}
                    aria-label={compact ? label : undefined}
                    className={cn(
                      'group relative flex h-10 w-full items-center gap-3 rounded-md px-3 text-left text-body transition-colors duration-150',
                      compact && 'justify-center px-0',
                      active ? 'font-medium text-fg' : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
                    )}
                  >
                    {active && (
                      <m.span layoutId={layoutId} className="absolute inset-0 rounded-md border border-brand/25 bg-brand-soft" transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}>
                        <span className="absolute top-2 bottom-2 -left-3 w-1 rounded-r-full bg-brand-gradient" />
                      </m.span>
                    )}
                    <Icon aria-hidden className={cn('relative size-[18px] shrink-0 transition-colors', active ? 'text-brand' : 'text-fg-subtle group-hover:text-fg-muted')} />
                    {!compact && <span className="relative truncate">{label}</span>}
                  </button>
                </Tooltip>
              )
            })}
          </div>
        </div>
      ))}
    </nav>
  )
}

/** Desktop rail: expanded (240px) or icon-only (72px). Hidden below md, where MobileNav is used. */
export function Sidebar({ page, onNavigate, expanded, onToggle }: { page: Page; onNavigate: (p: Page) => void; expanded: boolean; onToggle: () => void }) {
  return (
    <aside
      className={cn(
        'sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-bg-elevated/80 backdrop-blur-xl transition-[width] duration-250 ease-(--ease-soft) md:flex',
        expanded ? 'w-60' : 'w-[72px]',
      )}
    >
      <Brand compact={!expanded} />
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden"><NavList page={page} onNavigate={onNavigate} compact={!expanded} layoutId="nav-active-desktop" /></div>
      <div className="border-t border-border p-3">
        <Tooltip content="展开侧栏" disabled={expanded}>
          <button
            type="button"
            onClick={onToggle}
            aria-label={expanded ? '收起侧栏' : '展开侧栏'}
            aria-expanded={expanded}
            className={cn('flex h-9 w-full items-center gap-2 rounded-md px-3 text-caption text-fg-subtle transition-colors hover:bg-surface-2 hover:text-fg', !expanded && 'justify-center px-0')}
          >
            {expanded ? <><ChevronsLeft className="size-4" />收起侧栏</> : <ChevronsRight className="size-4" />}
          </button>
        </Tooltip>
      </div>
    </aside>
  )
}

/** Below md: slide-in drawer (Radix Dialog: focus trap, Esc, scroll lock). */
export function MobileNav({ page, onNavigate, open, onOpenChange }: { page: Page; onNavigate: (p: Page) => void; open: boolean; onOpenChange: (v: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild forceMount>
              <m.div className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
            </Dialog.Overlay>
            <Dialog.Content asChild forceMount aria-describedby={undefined}>
              <m.div
                className="fixed inset-y-0 left-0 z-50 flex w-[min(80vw,288px)] flex-col border-r border-border bg-bg-elevated shadow-raised md:hidden"
                initial={{ x: '-100%' }} animate={{ x: 0 }} exit={{ x: '-100%' }} transition={{ duration: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
              >
                <Dialog.Title className="sr-only">导航</Dialog.Title>
                <div className="flex items-center justify-between pr-3"><Brand compact={false} />
                  <Dialog.Close aria-label="关闭导航" className="grid size-9 place-items-center rounded-md text-fg-muted hover:bg-surface-3 hover:text-fg"><X className="size-4" /></Dialog.Close>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto"><NavList page={page} onNavigate={p => { onNavigate(p); onOpenChange(false) }} compact={false} layoutId="nav-active-mobile" /></div>
              </m.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  )
}
