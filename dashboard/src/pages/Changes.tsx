import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { loadChanges, loadModels, useData } from '../lib/data'
import type { ChangeCategory, ChangeEvent } from '../lib/data'

const loadChangeFeed = () => loadChanges()

const CATEGORY_LABEL: Record<ChangeCategory, string> = {
  model_added: 'Model added',
  benchmark_changed: 'Benchmark changed',
  price_validity_changed: 'Price validity',
  alias_first_seen: 'Alias first seen',
  source_refreshed: 'Source refreshed',
}

function formatValue(value: Record<string, unknown> | null): string {
  if (!value) return 'Unavailable'
  return Object.entries(value).map(([key, entry]) => `${key}: ${String(entry ?? 'Unavailable')}`).join(' · ')
}

function modelIdForEvent(event: ChangeEvent): number | null {
  const modelId = Number(event.after?.modelId)
  return Number.isFinite(modelId) && modelId > 0 ? modelId : null
}

export default function Changes() {
  const { data: changes, loading, error } = useData(loadChangeFeed)
  const { data: models, loading: modelsLoading, error: modelsError } = useData(loadModels)
  const [category, setCategory] = useState<ChangeCategory | 'all'>('all')
  const [query, setQuery] = useState('')
  const modelById = useMemo(() => new Map((models ?? []).map((model) => [model.id, model])), [models])
  const modelBySlug = useMemo(() => new Map((models ?? []).map((model) => [model.slug, model])), [models])
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (changes?.events ?? []).filter((event) => {
      if (category !== 'all' && event.category !== category) return false
      const model = modelById.get(modelIdForEvent(event) ?? -1) ?? modelBySlug.get(event.entityId)
      return !needle || [event.entityId, event.sourceId, model?.name, model?.slug]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle))
    })
  }, [category, changes, modelById, modelBySlug, query])

  if (loading || modelsLoading) return <div className="py-16 text-center text-xs text-neutral-500">Loading recorded changes…</div>
  if (error || modelsError) return <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4 text-sm text-red-300">Could not load changes: {error ?? modelsError}</div>
  if (!changes || !models) return null

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold text-neutral-100">Recorded changes</h1>
            <p className="mt-1 text-xs text-neutral-500">Derived from stored model records, snapshots, benchmark results, prices, and aliases. Generated {changes.generatedAt.slice(0, 10)}.</p>
            {changes.truncated ? <p className="mt-1 text-xs text-amber-300/80">Showing the newest 1,000 events per category from {changes.totalEvents.toLocaleString()} recorded changes.</p> : null}
          </div>
          <div className="text-xs text-neutral-500">{visible.length.toLocaleString()} shown</div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search entity or source…" className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-200 placeholder-neutral-600 outline-none focus:border-neutral-500 sm:w-72" />
          <select value={category} onChange={(event) => setCategory(event.target.value as ChangeCategory | 'all')} className="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-200 outline-none focus:border-neutral-500">
            <option value="all">All categories</option>
            {Object.entries(CATEGORY_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      </section>

      {visible.length === 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 py-16 text-center text-sm text-neutral-500">No recorded changes match these filters.</div>
      ) : (
        <section className="overflow-hidden rounded-lg border border-neutral-800 bg-neutral-900">
          {visible.map((event, index) => {
            const model = modelById.get(modelIdForEvent(event) ?? -1) ?? modelBySlug.get(event.entityId)
            return (
              <article key={`${event.category}:${event.entityId}:${event.observedAt}:${index}`} className="grid gap-3 border-b border-neutral-800 p-4 last:border-b-0 md:grid-cols-[10rem_minmax(12rem,1fr)_minmax(16rem,2fr)]">
                <div>
                  <div className="text-xs font-medium text-neutral-300">{CATEGORY_LABEL[event.category]}</div>
                  <time className="mt-1 block text-xs text-neutral-500">{event.observedAt.slice(0, 10)}</time>
                </div>
                <div className="min-w-0">
                  <div className="text-sm text-neutral-100">{model ? <Link to={`/models/${model.slug}`} className="hover:text-white hover:underline">{model.name}</Link> : event.entityId}</div>
                  <div className="mt-1 truncate text-xs text-neutral-500">{event.entityId}</div>
                </div>
                <div className="space-y-1 text-xs">
                  <div className="text-neutral-400"><span className="text-neutral-600">Before </span>{formatValue(event.before)}</div>
                  <div className="text-neutral-200"><span className="text-neutral-600">After </span>{formatValue(event.after)}</div>
                  <div className="pt-1 text-neutral-500">
                    {event.sourceUrl ? <a href={event.sourceUrl} target="_blank" rel="noreferrer" className="hover:text-neutral-300 hover:underline">{event.sourceId ?? 'Source'}</a> : event.sourceId ?? 'No source URL'}
                    {event.snapshotId != null ? ` · snapshot ${event.snapshotId}` : ''}
                    {event.selfReported != null ? ` · ${event.selfReported ? 'self-reported' : 'independent'}` : ''}
                    {event.evalCondition ? ' · evaluation conditions recorded' : ''}
                  </div>
                </div>
              </article>
            )
          })}
        </section>
      )}
    </div>
  )
}
