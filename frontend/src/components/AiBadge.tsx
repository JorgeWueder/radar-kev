import { Sparkle } from '@phosphor-icons/react'

/** Marca visible de todo contenido generado por IA. */
export function AiBadge({ model }: { model?: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-sunken px-1.5 py-0.5 text-[11px] font-medium text-muted">
      <Sparkle size={12} weight="fill" aria-hidden /> Generado por IA{model ? ` · ${model}` : ''}
    </span>
  )
}
