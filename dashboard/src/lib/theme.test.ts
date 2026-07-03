import { describe, expect, test } from 'bun:test'
import { shortName } from './theme'

const CASES = [
  {
    slug: 'google/gemini-1-0-ultra',
    expected: 'Gemini 1.0 Ultra',
    contract: 'keeps the Gemini brand on provider-prefixed slugs while preserving dotted versions',
  },
  {
    slug: 'google/gemma-3-270m',
    expected: 'Gemma 3 270M',
    contract: 'keeps the Gemma brand on provider-prefixed slugs without treating parameter counts as decimals',
  },
  {
    slug: 'anthropic/claude-4-sonnet',
    expected: 'Sonnet 4',
    contract: 'continues to shorten Claude family slugs to tier and generation',
  },
  {
    slug: 'openai/gpt-5',
    expected: 'GPT 5',
    contract: 'preserves the GPT brand casing when formatting OpenAI slugs',
  },
] as const

describe('shortName display formatting', () => {
  for (const { slug, expected, contract } of CASES) {
    test(contract, () => {
      expect(shortName(slug)).toBe(expected)
    })
  }
})
