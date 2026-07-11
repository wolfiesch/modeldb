import type { ReactNode } from 'react'

export type ChartStatus = 'loading' | 'error' | 'empty' | 'ready'

/** Derive a single status from the usual data flags. */
export function resolveChartStatus(opts: {
  loading: boolean
  error: string | null | undefined
  hasData: boolean
  rowCount: number
}): ChartStatus {
  if (opts.loading) return 'loading'
  if (opts.error) return 'error'
  if (!opts.hasData || opts.rowCount === 0) return 'empty'
  return 'ready'
}

export interface ChartFooterProps {
  /** Source label, e.g. "LMArena + Artificial Analysis". */
  source?: string
  /** Rows currently plotted. */
  shown?: number
  /** Total rows available before filtering. */
  total?: number
  /** Data-as-of timestamp (already formatted). */
  updated?: string
  /** Extra note, e.g. active filters or a metric definition. */
  note?: string
}

/** Compact provenance footer shown under a chart/card. */
export function ChartFooter({ source, shown, total, updated, note }: ChartFooterProps) {
  const parts: string[] = []
  if (source) parts.push(source)
  if (shown != null) parts.push(total != null ? `${shown} / ${total} shown` : `${shown} shown`)
  if (updated) parts.push(`Updated ${updated}`)
  if (parts.length === 0 && !note) return null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-neutral-800/60 pt-2 text-[10px] text-neutral-600">
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-2">
          {i > 0 && <span className="text-neutral-700">·</span>}
          {p}
        </span>
      ))}
      {note && (
        <span className="flex items-center gap-2">
          {parts.length > 0 && <span className="text-neutral-700">·</span>}
          <span className="text-neutral-500">{note}</span>
        </span>
      )}
    </div>
  )
}

export interface ChartStateProps {
  status: ChartStatus
  /** Message for the loading state. */
  loadingLabel?: string
  /** Message for the error state (falls back to a generic line). */
  errorLabel?: string | null
  /** Message for the empty state. */
  emptyLabel?: string
  /** Min height so loading/empty/error occupy the chart's footprint. */
  minHeight?: number
  /** Provenance footer, rendered under children when ready. */
  footer?: ChartFooterProps
  children: ReactNode
}

/**
 * Wraps a chart body with explicit loading / empty / error / ready states so a
 * chart never silently renders bare axes. Render the chart as `children`; it is
 * only shown when `status === 'ready'`.
 */
export default function ChartState({
  status,
  loadingLabel = 'Loading…',
  errorLabel,
  emptyLabel = 'No data matches the current filters.',
  minHeight = 320,
  footer,
  children,
}: ChartStateProps) {
  if (status !== 'ready') {
    const message =
      status === 'loading' ? loadingLabel : status === 'error' ? (errorLabel ?? 'Failed to load data.') : emptyLabel
    const tone =
      status === 'error' ? 'text-red-400' : status === 'loading' ? 'text-neutral-500' : 'text-neutral-500'
    return (
      <div className="flex items-center justify-center px-4 text-center text-sm" style={{ minHeight }}>
        <div className={tone}>
          {status === 'loading' && (
            <span className="mr-2 inline-block h-3 w-3 animate-pulse rounded-full bg-neutral-600 align-middle" />
          )}
          {message}
        </div>
      </div>
    )
  }
  return (
    <>
      {children}
      {footer && <ChartFooter {...footer} />}
    </>
  )
}
