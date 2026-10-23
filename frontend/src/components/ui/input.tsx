import { ChevronDown } from 'lucide-react'
import type { InputHTMLAttributes, ReactNode, Ref, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

const control = cn(
  'w-full rounded-md border border-border-strong bg-surface-2/70 px-3 py-2 text-body text-fg placeholder:text-fg-subtle',
  'outline-none transition-[border-color,box-shadow,background-color] duration-200 ease-(--ease-soft)',
  'hover:border-fg-subtle/60 focus:border-brand focus:bg-surface-2 focus:shadow-[0_0_0_4px_var(--brand-soft)]',
  'disabled:cursor-not-allowed disabled:opacity-55 read-only:bg-surface-3/50 read-only:focus:shadow-none',
  'aria-invalid:border-danger aria-invalid:focus:shadow-[0_0_0_4px_var(--danger-soft)]',
)

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  return <input className={cn(control, 'min-h-9', className)} {...props} />
}
export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(control, 'min-h-20 resize-y', className)} {...props} />
}
/** Native select (keeps form semantics, keyboard and change events) with themed chrome. */
export function Select({ className, wrapperClassName, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { wrapperClassName?: string }) {
  return (
    <span className={cn('relative block', wrapperClassName)}>
      <select className={cn(control, 'min-h-9 appearance-none pr-9 [&>option]:bg-surface [&>option]:text-fg', className)} {...props} />
      <ChevronDown aria-hidden className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-fg-subtle" />
    </span>
  )
}
/** Label + control + hint/error. The control is a child so its aria-label stays the accessible name. */
export function Field({ label, hint, error, children, className }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn('grid content-start gap-1.5 text-caption font-medium text-fg-muted', className)}>
      <span>{label}</span>
      {children}
      {error ? <span className="font-normal text-danger">{error}</span> : hint ? <span className="font-normal text-fg-subtle">{hint}</span> : null}
    </label>
  )
}
