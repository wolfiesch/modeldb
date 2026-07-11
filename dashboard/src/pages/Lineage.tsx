import { useMemo, useState } from 'react'
import { confidenceLabel, familyRelationships, groupAliases } from '../lib/lineage'
import { loadLineage, useData } from '../lib/data'
import type { LineageAlias, LineageIdentity } from '../lib/data'

function AliasList({ aliases }: { aliases: LineageAlias[] }) {
  const groups = groupAliases(aliases)
  if (!groups.length) return <p className="text-sm text-neutral-500">No source aliases recorded.</p>
  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <div key={group.sourceId} className="rounded-md border border-neutral-800 bg-neutral-900/50 p-3">
          <div className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">{group.sourceId}</div>
          {group.aliases.map((alias) => {
            const evidence = aliases.find((item) => item.sourceId === group.sourceId && item.alias === alias)
            return (
              <div key={alias} className="flex flex-wrap items-baseline gap-x-2 py-1 text-sm">
                <code className="text-neutral-200">{alias}</code>
                <span className="text-xs text-neutral-500">{evidence?.kind}</span>
                <span className="text-xs text-cyan-300/80">{confidenceLabel(evidence?.confidence ?? 0)}</span>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

function RelatedModels({ identity }: { identity: LineageIdentity }) {
  const relationships = familyRelationships(identity)
  const section = (label: string, peers: typeof relationships.predecessors, inferred: boolean) => (
    <section>
      <h3 className="text-xs font-medium uppercase tracking-wide text-neutral-500">{label}</h3>
      {inferred && (
        <p className="mt-1 text-xs text-amber-300/80">
          Inferred from the recorded family and release dates; not a vendor-declared relationship.
        </p>
      )}
      {peers.length ? (
        <ul className="mt-2 space-y-1 text-sm">
          {peers.map((peer) => (
            <li key={peer.modelId} className="flex justify-between gap-3 text-neutral-300">
              <code>{peer.canonicalSlug}</code>
              <span className="shrink-0 text-neutral-500">{peer.released ?? 'release date unavailable'}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-neutral-500">None recorded.</p>
      )}
    </section>
  )
  return (
    <div className="space-y-5">
      {section('Earlier family releases', relationships.predecessors, true)}
      {section('Later family releases', relationships.successors, true)}
      {section('Other family peers', relationships.undated, false)}
    </div>
  )
}

export default function Lineage() {
  const { data, loading, error } = useData(loadLineage)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const identities = useMemo(() => Object.values(data ?? {}).sort((a, b) => a.name.localeCompare(b.name)), [data])
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return needle ? identities.filter((identity) => [identity.name, identity.canonicalSlug, ...identity.aliases.map((alias) => alias.alias)].some((value) => value.toLowerCase().includes(needle))) : identities
  }, [identities, query])
  const selected = (selectedId && data?.[selectedId]) ?? matches[0] ?? null

  if (loading) return <div className="text-neutral-500">Loading lineage…</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!selected) return <div className="py-16 text-center text-neutral-500">No model identities are available.</div>

  const evaluationVariants = selected.aliases.filter((alias) => alias.kind === 'arena_model')
  const sourceAliases = selected.aliases.filter((alias) => alias.kind !== 'arena_model')
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-neutral-800 pb-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-cyan-300">Model identity graph</p>
          <h1 className="mt-1 text-2xl font-semibold text-neutral-100">Canonical model lineage</h1>
          <p className="mt-1 max-w-2xl text-sm text-neutral-500">Canonical records are distinct from the names supplied by sources and evaluation surfaces.</p>
        </div>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search canonical name or alias…" className="w-80 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 outline-none placeholder:text-neutral-600 focus:border-cyan-400" />
      </header>
      <div className="grid gap-5 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="max-h-[70vh] overflow-auto rounded-lg border border-neutral-800 bg-neutral-950 p-2">
          {matches.map((identity) => (
            <button
              type="button"
              key={identity.modelId}
              onClick={() => setSelectedId(String(identity.modelId))}
              className={`w-full rounded-md px-3 py-2 text-left ${identity.modelId === selected.modelId ? 'bg-cyan-400/10 text-cyan-100' : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'}`}
            >
              <span className="block truncate text-sm">{identity.name}</span>
              <code className="block truncate text-xs text-neutral-600">{identity.canonicalSlug}</code>
            </button>
          ))}
        </aside>
        <main className="space-y-5">
          <section className="rounded-lg border border-cyan-400/20 bg-gradient-to-br from-cyan-400/10 to-neutral-950 p-5">
            <p className="text-xs font-medium uppercase tracking-wide text-cyan-300">Canonical identity</p>
            <h2 className="mt-2 text-2xl font-semibold text-neutral-100">{selected.name}</h2>
            <code className="mt-1 block text-sm text-neutral-400">{selected.canonicalSlug}</code>
            <dl className="mt-5 grid gap-3 sm:grid-cols-3 text-sm">
              <div>
                <dt className="text-neutral-500">Developer</dt>
                <dd className="text-neutral-200">{selected.developerName ?? selected.developerId ?? 'Unknown'}</dd>
              </div>
              <div>
                <dt className="text-neutral-500">Family / generation</dt>
                <dd className="text-neutral-200">{[selected.family, selected.generation].filter(Boolean).join(' · ') || 'Not recorded'}</dd>
              </div>
              <div>
                <dt className="text-neutral-500">Release</dt>
                <dd className="text-neutral-200">{selected.released ?? 'Not recorded'}</dd>
              </div>
            </dl>
          </section>
          <div className="grid gap-5 xl:grid-cols-2">
            <section className="rounded-lg border border-neutral-800 p-5">
              <h2 className="font-medium text-neutral-100">Source aliases</h2>
              <p className="mb-4 mt-1 text-xs text-neutral-500">Names observed in source snapshots, with the method and confidence behind their canonical resolution.</p>
              <AliasList aliases={sourceAliases} />
            </section>
            <section className="rounded-lg border border-neutral-800 p-5">
              <h2 className="font-medium text-neutral-100">Evaluation variants</h2>
              <p className="mb-4 mt-1 text-xs text-neutral-500">Evaluation-specific source names are not canonical identities.</p>
              <AliasList aliases={evaluationVariants} />
            </section>
          </div>
          <section className="rounded-lg border border-neutral-800 p-5">
            <h2 className="font-medium text-neutral-100">Provider endpoints and provenance</h2>
            <div className="mt-3 space-y-2 text-sm">
              {selected.providerEndpoints.length ? (
                selected.providerEndpoints.map((endpoint, index) => (
                  <div key={`${endpoint.providerId}-${endpoint.endpointModelId}-${index}`} className="flex flex-wrap justify-between gap-2 border-b border-neutral-800 pb-2 last:border-0">
                    <code className="text-neutral-200">{endpoint.providerId} / {endpoint.endpointModelId}</code>
                    <span className="text-neutral-500">{[endpoint.surfaceType, endpoint.region, endpoint.fetchedAt].filter(Boolean).join(' · ')}</span>
                  </div>
                ))
              ) : (
                <p className="text-neutral-500">No provider endpoints recorded.</p>
              )}
            </div>
            <p className="mt-4 text-xs text-neutral-500">First observed: {selected.firstSeen ?? 'unknown'} · Last observed: {selected.lastSeen ?? 'unknown'} · Sources: {selected.sourceTypes.join(', ') || 'none recorded'}</p>
          </section>
          <section className="rounded-lg border border-neutral-800 p-5">
            <h2 className="font-medium text-neutral-100">Adjacent family releases</h2>
            <div className="mt-4">
              <RelatedModels identity={selected} />
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}
