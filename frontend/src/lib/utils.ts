import clsx, { type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'
// Teach tailwind-merge the custom @theme scales so `text-body` is a size (not a
// colour that would evict `text-fg`) and `shadow-card` is a shadow.
const twMerge = extendTailwindMerge({ extend: { theme: { text: ['display', 'title', 'body', 'caption'], shadow: ['card', 'raised', 'glow'] } } })
export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs))
