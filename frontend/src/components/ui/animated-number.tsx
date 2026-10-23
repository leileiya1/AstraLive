import { useEffect } from 'react'
import { useReducedMotion, useSpring, useTransform } from 'motion/react'
import * as m from 'motion/react-m'

const round = (n: number) => Math.round(n).toLocaleString('zh-CN')

/** Rolls to the new value with a short spring; renders statically under reduced motion. */
export function AnimatedNumber({ value, format = round, className }: { value: number; format?: (n: number) => string; className?: string }) {
  const reduce = useReducedMotion()
  const spring = useSpring(value, { stiffness: 140, damping: 22, mass: 0.6 })
  useEffect(() => { spring.set(value) }, [spring, value])
  const text = useTransform(spring, format)
  if (reduce) return <span className={className}>{format(value)}</span>
  return <m.span className={className}>{text}</m.span>
}
