import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { loadModels, useData, type Model } from '../lib/data'
import LabLogo from './LabLogo'
import { fmtElo, fmtPrice, fmtTokens, fmtDate, fmtPercent } from '../lib/format'

interface DrawerContextValue {
  /** Open the drawer for a model slug (e.g. "anthropic/claude-opus-4-6"). */
  openModel: (slug: string) => void
  /** Currently open slug, or null. */
  openSlug: string | null
}

const DrawerContext = createContext<DrawerContextValue | null>(null)

/** Hook to open the shared model drawer from any page. */
export function useModelDrawer(): DrawerContextValue {
  const ctx = useContext(DrawerContext)
  if (!ctx) return { openModel: () => {}, openSlug: null }
  return ctx
}

function DrawerBody({ slug, onClose }: { slug: string; onClose: () => void }) {
  const { data: models } = useData(loadModels)
  const model: Model | undefined = useMemo(
    () => models?.find((m) => m.slug === slug),
    [models, slug],
  )

  if (!model) {
    return (
      <div className="p-6 text-sm text-neutral-500">
        Loading model…
      </div>
    )
  }

  const elo = model.scores?.lmarena_text_overall?.score ?? null
  const scoredCount = model.scores ? Object.keys(model.scores).length : 0

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between border-b border-neutral-800 p-5">
        <div className="flex items-center gap-3">
          <LabLogo dev={model.dev} size={24} />
          <div>
            <div className="text-base font-semibold text-neutral-100">{model.name}</div>
            <div className="text-xs text-neutral-500">{model.slug}</div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-neutral-800 p-4 text-[11px]">
        <span className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-300">
          {model.open === 1 ? 'Open weights' : 'Closed'}
        </span>
        {model.released && (
          <span className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-300">
            {fmtDate(model.released)}
          </span>
        )}
        {model.inMod && model.inMod.length > 0 && (
          <span className="rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-neutral-300">
            {model.inMod.join(', ')}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-px bg-neutral-800 p-px">
        <Metric label="Arena ELO" value={fmtElo(elo)} />
        <Metric label="Scored signals" value={String(scoredCount)} />
        <Metric label="Price in / 1M" value={fmtPrice(model.priceIn)} />
        <Metric label="Price out / 1M" value={fmtPrice(model.priceOut)} />
        <Metric label="Context" value={fmtTokens(model.ctx)} />
        <Metric label="Max output" value={fmtTokens(model.maxOut)} />
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        <div className="mb-2 text-[10px] uppercase tracking-wider text-neutral-500">Top benchmarks</div>
        <div className="space-y-1">
          {model.scores &&
            Object.entries(model.scores)
              .slice(0, 8)
              .map(([id, s]) => (
                <div key={id} className="flex items-center justify-between text-xs">
                  <span className="truncate text-neutral-400">{id}</span>
                  <span className="ml-2 font-medium text-neutral-200">
                    {s.score >= 100 ? fmtElo(s.score) : s.score < 1 ? fmtPercent(s.score * 100) : s.score.toFixed(1)}
                  </span>
                </div>
              ))}
        </div>
      </div>

      <div className="border-t border-neutral-800 p-4">
        <Link
          to={`/models/${model.slug.split('/').map(encodeURIComponent).join('/')}`}
          onClick={onClose}
          className="block rounded bg-neutral-100 px-3 py-2 text-center text-sm font-medium text-neutral-900 hover:bg-white"
        >
          View full profile
        </Link>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-neutral-950 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wider text-neutral-500">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-neutral-100">{value}</div>
    </div>
  )
}

/** Provider + drawer surface. Wrap the app; call `useModelDrawer().openModel`. */
export function ModelDrawerProvider({ children }: { children: ReactNode }) {
  const [openSlug, setOpenSlug] = useState<string | null>(null)
  const openModel = useCallback((slug: string) => setOpenSlug(slug), [])
  const close = useCallback(() => setOpenSlug(null), [])
  const value = useMemo<DrawerContextValue>(() => ({ openModel, openSlug }), [openModel, openSlug])

  return (
    <DrawerContext.Provider value={value}>
      {children}
      {openSlug && (
        <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/50" onClick={close} />
          <div className="relative z-10 h-full w-96 max-w-[90vw] overflow-hidden border-l border-neutral-800 bg-neutral-950 shadow-2xl">
            <DrawerBody slug={openSlug} onClose={close} />
          </div>
        </div>
      )}
    </DrawerContext.Provider>
  )
}
