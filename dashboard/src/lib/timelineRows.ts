import type { EloFile, Model } from './data'

const INFER_ACTIVE_WINDOW_MS = 90 * 24 * 60 * 60 * 1000

export interface TimelineRow {
  model: Model
  releaseMs: number
  observedEndMs: number | null
  displayEndMs: number
  released: string
  observedThrough: string | null
  displayEnd: string
  shownThrough: string
  active: boolean
  retired: boolean
}

function parseDateMs(value: string | null): number | null {
  if (!value) return null
  const ms = Date.parse(value)
  return Number.isFinite(ms) ? ms : null
}

export function formatTimelineDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}


export function buildTimelineRows(
  models: Model[],
  eloSeries: EloFile['series'],
  asOfMs: number,
): TimelineRow[] {
  const observedEndByModel = new Map<number, number>()
  for (const series of eloSeries) {
    const last = series.t.at(-1)
    if (last != null && Number.isFinite(last)) {
      observedEndByModel.set(series.modelId, Math.min(last, asOfMs))
    }
  }

  return models
    .map((model) => {
      const releaseMs = parseDateMs(model.released)
      if (releaseMs == null || releaseMs > asOfMs) return null

      const observedEndMs = observedEndByModel.get(model.id) ?? null
      const stability = model.stability?.toLowerCase()
      const retired = stability === 'deprecated' || stability === 'retired'
      const explicitlyCurrent =
        stability === 'latest_alias' ||
        stability === 'latest' ||
        stability === 'preview' ||
        stability === 'stable' ||
        stability === 'canonical'
      const recentlyReleased = releaseMs >= asOfMs - INFER_ACTIVE_WINDOW_MS
      const active = !retired && (explicitlyCurrent || recentlyReleased)
      const displayEndMs = active ? asOfMs : (observedEndMs ?? releaseMs)
      const shownThrough = formatTimelineDate(displayEndMs)

      return {
        model,
        releaseMs,
        observedEndMs,
        displayEndMs,
        released: formatTimelineDate(releaseMs),
        observedThrough: observedEndMs == null ? null : formatTimelineDate(observedEndMs),
        displayEnd: shownThrough,
        shownThrough,
        active,
        retired,
      }
    })
    .filter((row): row is TimelineRow => row != null)
    .sort((a, b) => b.releaseMs - a.releaseMs)
}
