import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { getLabMeta } from '../lib/labs'

export interface LabLogoProps {
  dev: string | null | undefined
  devName?: string | null
  size?: number | string
  showLabel?: boolean
  labelClassName?: string
  className?: string
  imgClassName?: string
  fallback?: ReactNode
  decorative?: boolean
  title?: string
  variant?: 'dark' | 'tile' | 'default'
}

function initialsFor(label: string): string {
  const words = label.match(/[\p{L}\p{N}]+/gu) ?? []
  const initials = words.slice(0, 2).map((word) => word.charAt(0).toUpperCase()).join('')
  return initials || '?'
}

export function LabLogo({
  dev,
  devName,
  size = 24,
  showLabel = false,
  labelClassName,
  className,
  imgClassName,
  fallback,
  decorative = false,
  title,
  variant = 'dark',
}: LabLogoProps) {
  const meta = getLabMeta(dev, devName)
  const [loadFailed, setLoadFailed] = useState(false)
  const accessibleLabel = title ?? meta.label
  const imageIsHiddenFromA11y = decorative || showLabel
  const imageAlt = imageIsHiddenFromA11y ? '' : accessibleLabel
  const logoStyle: CSSProperties = { width: size, height: size }
  const logoSrc =
    variant === 'tile'
      ? meta.markTilePath ?? meta.markPath
      : variant === 'default'
        ? meta.markPath
        : meta.markDarkPath ?? meta.markPath
  const canRenderImage = Boolean(logoSrc && !loadFailed)

  useEffect(() => {
    setLoadFailed(false)
  }, [logoSrc])

  const fallbackNode = fallback ?? initialsFor(meta.label)

  return (
    <span
      className={['inline-flex items-center gap-2 align-middle', className].filter(Boolean).join(' ')}
      title={title}
    >
      {canRenderImage ? (
        <img
          src={logoSrc}
          alt={imageAlt}
          aria-hidden={imageIsHiddenFromA11y ? true : undefined}
          className={['shrink-0 object-contain', imgClassName].filter(Boolean).join(' ')}
          style={logoStyle}
          onError={() => setLoadFailed(true)}
        />
      ) : (
        <span
          aria-hidden={imageIsHiddenFromA11y ? true : undefined}
          role={imageIsHiddenFromA11y ? undefined : 'img'}
          aria-label={imageIsHiddenFromA11y ? undefined : accessibleLabel}
          className={[
            'inline-flex shrink-0 items-center justify-center rounded-md text-[0.6rem] font-semibold leading-none text-white',
            imgClassName,
          ].filter(Boolean).join(' ')}
          style={{ ...logoStyle, backgroundColor: meta.colorDark }}
        >
          {fallbackNode}
        </span>
      )}
      {showLabel ? <span className={labelClassName}>{meta.label}</span> : null}
    </span>
  )
}

export default LabLogo
