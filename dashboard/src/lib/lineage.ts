import type { LineageAlias, LineageFamilyPeer, LineageIdentity } from './data'

export interface AliasGroup {
  sourceId: string
  aliases: string[]
}

export function groupAliases(aliases: LineageAlias[]): AliasGroup[] {
  const aliasesBySource = new Map<string, string[]>()
  for (const { sourceId, alias } of aliases) {
    const sourceAliases = aliasesBySource.get(sourceId) ?? []
    sourceAliases.push(alias)
    aliasesBySource.set(sourceId, sourceAliases)
  }
  return [...aliasesBySource.entries()]
    .map(([sourceId, sourceAliases]) => ({ sourceId, aliases: [...new Set(sourceAliases)].sort() }))
    .sort((a, b) => a.sourceId.localeCompare(b.sourceId))
}

export function confidenceLabel(confidence: number): string {
  if (confidence >= 1) return 'Exact match'
  if (confidence >= 0.75) return 'High confidence'
  if (confidence >= 0.5) return 'Moderate confidence'
  return 'Needs review'
}

export interface FamilyRelationships {
  predecessors: LineageFamilyPeer[]
  successors: LineageFamilyPeer[]
  undated: LineageFamilyPeer[]
}

export function familyRelationships(identity: LineageIdentity): FamilyRelationships {
  const predecessors: LineageFamilyPeer[] = []
  const successors: LineageFamilyPeer[] = []
  const undated: LineageFamilyPeer[] = []
  for (const peer of identity.familyPeers) {
    if (!peer.released || !identity.released || peer.released === identity.released) {
      undated.push(peer)
    } else if (peer.released < identity.released) {
      predecessors.push(peer)
    } else {
      successors.push(peer)
    }
  }
  const byRelease = (a: LineageFamilyPeer, b: LineageFamilyPeer) =>
    (a.released ?? '').localeCompare(b.released ?? '') || a.name.localeCompare(b.name)
  return {
    predecessors: predecessors.sort(byRelease),
    successors: successors.sort(byRelease),
    undated: undated.sort((a, b) => a.name.localeCompare(b.name)),
  }
}
