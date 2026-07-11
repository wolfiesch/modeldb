import { describe, expect, test } from 'bun:test'
import type { LineageIdentity } from './data'
import { confidenceLabel, familyRelationships, groupAliases } from './lineage'

function identity(overrides: Partial<LineageIdentity> = {}): LineageIdentity {
  return {
    modelId: 1,
    canonicalSlug: 'acme/atlas-2',
    name: 'Atlas 2',
    developerId: 'acme',
    developerName: 'Acme',
    family: 'Atlas',
    generation: '2',
    tier: null,
    released: '2025-06-01',
    aliases: [],
    sourceTypes: [],
    providerEndpoints: [],
    firstSeen: '2025-06-01',
    lastSeen: '2025-07-01',
    familyPeers: [],
    ...overrides,
  }
}

describe('lineage identity derivation', () => {
  test('groups source aliases separately from canonical identity', () => {
    const grouped = groupAliases([
      { sourceId: 'openrouter', alias: 'acme/atlas-2', kind: 'provider', method: 'exact', confidence: 1, firstSeen: '2025-06-01', lastSeen: '2025-07-01' },
      { sourceId: 'huggingface', alias: 'acme/Atlas-2-Instruct', kind: 'artifact', method: 'normalized', confidence: 0.8, firstSeen: '2025-06-02', lastSeen: '2025-07-01' },
    ])

    expect(grouped).toEqual([
      { sourceId: 'huggingface', aliases: ['acme/Atlas-2-Instruct'] },
      { sourceId: 'openrouter', aliases: ['acme/atlas-2'] },
    ])
  })

  test('uses honest confidence labels for resolution evidence', () => {
    expect(confidenceLabel(1)).toBe('Exact match')
    expect(confidenceLabel(0.8)).toBe('High confidence')
    expect(confidenceLabel(0.49)).toBe('Needs review')
  })

  test('orders inferred family relationships by actual release date', () => {
    const relationships = familyRelationships(identity({
      familyPeers: [
        { modelId: 3, canonicalSlug: 'acme/atlas-3', name: 'Atlas 3', released: '2026-01-01', generation: '3' },
        { modelId: 0, canonicalSlug: 'acme/atlas-1', name: 'Atlas 1', released: '2024-01-01', generation: '1' },
        { modelId: 4, canonicalSlug: 'acme/atlas-undated', name: 'Atlas undated', released: null, generation: null },
      ],
    }))

    expect(relationships).toEqual({
      predecessors: [{ modelId: 0, canonicalSlug: 'acme/atlas-1', name: 'Atlas 1', released: '2024-01-01', generation: '1' }],
      successors: [{ modelId: 3, canonicalSlug: 'acme/atlas-3', name: 'Atlas 3', released: '2026-01-01', generation: '3' }],
      undated: [{ modelId: 4, canonicalSlug: 'acme/atlas-undated', name: 'Atlas undated', released: null, generation: null }],
    })
  })
})
