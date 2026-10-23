import { Slot } from '@radix-ui/react-slot'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, Ref } from 'react'
import { cn } from '../../lib/utils'

type Variant = 'default' | 'outline' | 'danger' | 'ghost' | 'subtle'
type Size = 'sm' | 'md' | 'lg' | 'icon'
type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
  loading?: boolean
  asChild?: boolean
  ref?: Ref<HTMLButtonElement>
}

const variants: Record<Variant, string> = {
  default: 'bg-brand-gradient text-brand-fg shadow-[0_6px_20px_-8px_var(--brand)] hover:brightness-110 hover:shadow-glow',
  outline: 'border border-border-strong bg-surface-2/60 text-fg hover:border-brand/50 hover:bg-surface-3',
  danger: 'bg-danger-solid text-white shadow-[0_6px_20px_-10px_var(--danger)] hover:brightness-110',
  ghost: 'text-fg-muted hover:bg-surface-3 hover:text-fg',
  subtle: 'bg-brand-soft text-brand hover:bg-brand/20',
}
const sizes: Record<Size, string> = {
  sm: 'min-h-8 gap-1.5 rounded-md px-2.5 text-caption',
  md: 'min-h-9 gap-2 rounded-md px-3.5 text-body',
  lg: 'min-h-11 gap-2 rounded-lg px-5 text-body',
  icon: 'size-9 rounded-md',
}

export function Button({ className, variant = 'default', size = 'md', loading = false, asChild = false, disabled, children, ...props }: Props) {
  const Comp = asChild ? Slot : 'button'
  return (
    <Comp
      className={cn(
        'inline-flex shrink-0 select-none items-center justify-center font-medium whitespace-nowrap',
        'transition-[transform,filter,background-color,border-color,box-shadow,color] duration-150 ease-(--ease-soft)',
        'active:scale-[0.97] disabled:pointer-events-none disabled:opacity-45 disabled:shadow-none',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring',
        variants[variant], sizes[size], className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {asChild ? children : <>{loading && <Loader2 aria-hidden className="size-4 animate-spin" />}{children}</>}
    </Comp>
  )
}
