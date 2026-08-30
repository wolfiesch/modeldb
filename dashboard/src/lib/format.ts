// Shared value formatters. Use compact human formats in tables/labels and
// exact raw values only in tooltips/detail. Every metric type has one formatter
// so numbers look consistent across every page.

const NBSP = '\u00A0'

/** Percentile / percent-like 0..100 value → "98.4%". */
export function fmtPercent(value: number | null | undefined, digits = 1): string {
 if (value == null || !Number.isFinite(value)) return '—'
 return `${value.toFixed(digits)}%`
}

/** ELO / integer-ish score → "1,494". */
export function fmtElo(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value)) return '—'
 return Math.round(value).toLocaleString('en-US')
}

/** Signed delta → "+3" / "-6" / "0". */
export function fmtDelta(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value)) return '—'
 const rounded = Math.round(value)
 if (rounded > 0) return `+${rounded}`
 return String(rounded)
}

/** Tailwind text color class for a delta (positive green, negative red). */
export function deltaColorClass(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value) || value === 0) return 'text-neutral-500'
 return value > 0 ? 'text-emerald-400' : 'text-red-400'
}

/** Generic unitless benchmark score. */
export function fmtScore(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value)) return '—'
 const abs = Math.abs(value)
 if (abs >= 100) return Math.round(value).toLocaleString('en-US')
 if (abs >= 10) return value.toFixed(1)
 // 0..10 range (fractions / indices): up to 3 sig decimals, no trailing zeros.
 return parseFloat(value.toFixed(3)).toString()
}
const PERCENTAGE_METRICS: Record<string, true> = {
 accuracy: true,
 f1: true,
 pass_rate: true,
 pass_rate_2: true,
 percent: true,
 percent_correct: true,
 percent_resolved: true,
 percentage: true,
}

export function benchmarkMetricKind(metric: string | null | undefined): 'elo' | 'percent' | 'score' {
 if (!metric) return 'score'
 const normalized = metric.trim().toLowerCase().replace(/[-\s]+/g, '_')
 if (normalized.includes('elo')) return 'elo'
 if (PERCENTAGE_METRICS[normalized] || normalized.startsWith('percent_')) return 'percent'
 return 'score'
}

/** Benchmark score formatted from its canonical metric, without magnitude guessing. */
export function fmtBenchmarkScore(
 value: number | null | undefined,
 metric: string | null | undefined,
): string {
 switch (benchmarkMetricKind(metric)) {
  case 'elo':
   return fmtElo(value)
  case 'percent':
   return fmtPercent(value)
  case 'score':
   return fmtScore(value)
 }
}

/** Dollars per 1M tokens → "$5", "$0.43", "$1.50". */
export function fmtPrice(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value)) return '—'
 if (value === 0) return 'Free'
 if (value < 1) return `$${value.toFixed(2)}`
 if (Number.isInteger(value)) return `$${value}`
 return `$${value.toFixed(2)}`
}

/** Context / token counts → "1.05M", "128K", "512". */
export function fmtTokens(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value)) return '—'
 if (value >= 1_000_000) return `${parseFloat((value / 1_000_000).toFixed(2))}M`
 if (value >= 1_000) return `${parseFloat((value / 1_000).toFixed(1))}K`
 return String(Math.round(value))
}

/** Throughput → "195 tok/s". */
export function fmtTps(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value)) return '—'
 return `${value.toFixed(value >= 100 ? 0 : 1)}${NBSP}tok/s`
}

/** Latency seconds → "0.42s". */
export function fmtSeconds(value: number | null | undefined, digits = 2): string {
 if (value == null || !Number.isFinite(value)) return '—'
 return `${value.toFixed(digits)}s`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** ISO date "2026-07-03" → "Jul 3, 2026". Passes through if unparseable. */
export function fmtDate(value: string | null | undefined): string {
 if (!value) return '—'
 const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
 if (!m) return value
 const year = Number(m[1])
 const month = Number(m[2]) - 1
 const day = Number(m[3])
 if (month < 0 || month > 11) return value
 return `${MONTHS[month]} ${day}, ${year}`
}

/** Full timestamp → "Jul 3, 2026 7:04 AM". Passes through if unparseable. */
export function fmtDateTime(value: string | null | undefined): string {
 if (!value) return '—'
 const d = new Date(value)
 if (Number.isNaN(d.getTime())) return value
 const date = fmtDate(d.toISOString().slice(0, 10))
 let hours = d.getHours()
 const minutes = d.getMinutes().toString().padStart(2, '0')
 const ampm = hours >= 12 ? 'PM' : 'AM'
 hours = hours % 12 || 12
 return `${date} ${hours}:${minutes} ${ampm}`
}

/** Compact integer with thousands separators → "94,827". */
export function fmtCount(value: number | null | undefined): string {
 if (value == null || !Number.isFinite(value)) return '—'
 return Math.round(value).toLocaleString('en-US')
}
