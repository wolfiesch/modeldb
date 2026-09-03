import { afterEach, describe, expect, test } from 'bun:test'
import { loadBenchmarks, loadPrices } from './data'

const originalFetch = globalThis.fetch

function stubFetch(responders: Array<() => Promise<Response>>) {
  let calls = 0
  globalThis.fetch = async () => {
    const respond = responders[Math.min(calls, responders.length - 1)]
    calls += 1
    return respond()
  }
  return () => calls
}

afterEach(() => {
  globalThis.fetch = originalFetch
})

const ok = (body: unknown) => () => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
const unavailable = () => Promise.resolve(new Response('unavailable', { status: 503 }))

describe('fetchJson module cache', () => {
  test('a rejected fetch is evicted so the next call retries', async () => {
    const fetchCount = stubFetch([unavailable, ok([])])

    await expect(loadBenchmarks()).rejects.toThrow('/data/benchmarks.json: HTTP 503')
    await expect(loadBenchmarks()).resolves.toEqual([])
    expect(fetchCount()).toBe(2)
  })

  test('a successful fetch stays cached across calls', async () => {
    const fetchCount = stubFetch([ok([{ modelId: 1, prices: [] }])])

    await expect(loadPrices()).resolves.toEqual([{ modelId: 1, prices: [] }])
    await expect(loadPrices()).resolves.toEqual([{ modelId: 1, prices: [] }])
    expect(fetchCount()).toBe(1)
  })
})
