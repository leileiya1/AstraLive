import { Slot } from '@radix-ui/react-slot'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'
type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'default'|'outline'|'danger'|'ghost'; asChild?: boolean }
export function Button({ className, variant='default', asChild=false, ...props }: Props) {
  const Comp = asChild ? Slot : 'button'
  return <Comp className={cn('inline-flex min-h-9 items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-500', variant === 'default' && 'bg-sky-600 text-white hover:bg-sky-700', variant === 'outline' && 'border border-slate-300 bg-white hover:bg-slate-50', variant === 'danger' && 'bg-rose-600 text-white hover:bg-rose-700', variant === 'ghost' && 'hover:bg-slate-100', className)} {...props}/>
}
