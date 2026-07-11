import { describe, expect, test } from 'bun:test'
import { NAVIGATION } from './navigation'

describe('research navigation', () => {
  test('exposes the portfolio research views exactly once', () => {
    const paths = NAVIGATION.map((item) => item.to)

    expect(paths.filter((path) => path === '/changes')).toHaveLength(1)
    expect(paths.filter((path) => path === '/lineage')).toHaveLength(1)
    expect(paths.filter((path) => path === '/about')).toHaveLength(1)
  })

  test('keeps labels unique for navigation and command search', () => {
    const labels = NAVIGATION.map((item) => item.label)

    expect(new Set(labels).size).toBe(labels.length)
  })
})
