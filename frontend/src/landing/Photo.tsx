// Foto del sitio público: WebP en dos tamaños (1200w y 2400w) con srcset/sizes y el tratamiento de DESIGN.md.
// Por defecto en blanco y negro con contraste; servers-* y fiber-* conservan su color.
import type { CSSProperties } from 'react'

const SIZES: Record<string, [number, number]> = {
  'cables-1-rodgerson': [2400, 1600],
  'fiber-1-muller': [2400, 1600],
  'fiber-2-umberto': [2400, 3613],
  'hero-1-baborak': [2400, 3600],
  'hero-2-yang': [2400, 3595],
  'hero-3-dittrich-bn': [2400, 1800],
  'hero-4-heerikhuize-bn': [2400, 1590],
  'servers-1-tyler': [2400, 1351],
  'servers-2-tyler': [2400, 1351],
  'servers-3-tyler': [2400, 1351],
  'servers-4-tyler': [2400, 1351],
  'servers-5-hanaoka': [2400, 1600],
  'soc-1-kostyuk': [2400, 1800],
  'soc-2-roose': [2400, 3600],
}

export type PhotoName = keyof typeof SIZES

const KEEP_COLOR = /^(servers|fiber)-/

export function Photo({
  name,
  alt,
  sizes,
  priority = false,
  className = '',
  style,
}: {
  name: PhotoName
  alt: string
  sizes: string
  priority?: boolean
  className?: string
  style?: CSSProperties
}) {
  const [w, h] = SIZES[name]
  const treat = KEEP_COLOR.test(name) ? undefined : 'grayscale(1) contrast(1.15)'
  return (
    <img
      src={`/img/${name}-1200.webp`}
      srcSet={`/img/${name}-1200.webp 1200w, /img/${name}-2400.webp 2400w`}
      sizes={sizes}
      width={w}
      height={h}
      alt={alt}
      loading={priority ? 'eager' : 'lazy'}
      decoding={priority ? 'sync' : 'async'}
      fetchPriority={priority ? 'high' : undefined}
      className={`object-cover ${className}`}
      style={{ filter: treat, ...style }}
    />
  )
}
