import type { Ref, InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'
const style = 'w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100'
export function Input({className,...props}:InputHTMLAttributes<HTMLInputElement> & {ref?: Ref<HTMLInputElement>}) { return <input className={cn(style,className)} {...props}/> }
export function Textarea({className,...props}:TextareaHTMLAttributes<HTMLTextAreaElement>) { return <textarea className={cn(style,className)} {...props}/> }
