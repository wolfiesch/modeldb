import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { loadModels, useData, type Model } from '../lib/data'
import { colorForDark } from '../lib/theme'

const PAGES = [
  { label: 'Overview', path: '/' },
  { label: 'Model Explorer', path: '/models' },
  { label: 'Arena over time', path: '/elo' },
  { label: 'Leaderboard race', path: '/race' },
  { label: 'Consensus matrix', path: '/consensus' },
  { label: 'Speed vs Quality', path: '/efficiency' },
  { label: 'Benchmarks', path: '/benchmarks' },
  { label: 'TPS Streams', path: '/tps' },
  { label: 'Compare', path: '/compare' },
  { label: 'Timeline', path: '/timeline' },
  { label: 'Landscape', path: '/landscape' },
]

type PageResult = {
  type: 'page'
  label: string
  path: string
}

type ModelResult = {
  type: 'model'
  model: Model
  path: string
}

type Result = PageResult | ModelResult


function searchResults(models: Model[] | null, queryText: string): Result[] {
  const query = queryText.trim().toLowerCase()
  const pages = PAGES.filter((page) => !query || page.label.toLowerCase().includes(query)).map<Result>((page) => ({
    type: 'page',
    label: page.label,
    path: page.path,
  }))

  const modelResults = query
    ? (models ?? [])
        .filter(
          (model) =>
            model.name.toLowerCase().includes(query) || model.slug.toLowerCase().includes(query),
        )
        .map<Result>((model) => ({
          type: 'model',
          model,
          path: `/models/${encodeURIComponent(model.slug)}`,
        }))
    : []

  return [...pages, ...modelResults].slice(0, 12)
}

export default function CommandPalette() {
  const navigate = useNavigate()
  const { data: models } = useData(loadModels)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const results = useMemo(() => searchResults(models, query), [models, query])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((isOpen) => !isOpen)
        return
      }
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setSelectedIndex(0)
    requestAnimationFrame(() => inputRef.current?.focus())
  }, [open])

  useEffect(() => {
    setSelectedIndex(0)
  }, [query])

  useEffect(() => {
    if (selectedIndex >= results.length) {
      setSelectedIndex(Math.max(0, results.length - 1))
    }
  }, [results.length, selectedIndex])

  function goTo(result: Result) {
    navigate(result.path)
    setOpen(false)
  }

  function onInputKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setSelectedIndex((index) => (results.length ? (index + 1) % results.length : 0))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setSelectedIndex((index) => (results.length ? (index - 1 + results.length) % results.length : 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const result = results[selectedIndex]
      if (result) goTo(result)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 px-4"
      role="presentation"
      onClick={() => setOpen(false)}
    >
      <div
        className="mx-auto mt-[15vh] max-w-lg rounded-lg border border-neutral-800 bg-neutral-900 p-4 shadow-2xl shadow-black/50"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(event) => event.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onInputKeyDown}
          className="w-full rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-neutral-100 outline-none placeholder:text-neutral-600 focus:border-neutral-600"
          placeholder="Search pages and models"
        />

        <div className="mt-3 max-h-96 overflow-y-auto">
          {results.length > 0 ? (
            <div className="space-y-1">
              {results.map((result, index) => {
                const isSelected = index === selectedIndex
                if (result.type === 'page') {
                  return (
                    <button
                      key={`page:${result.path}`}
                      type="button"
                      className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm ${
                        isSelected
                          ? 'bg-neutral-800 text-white'
                          : 'text-neutral-300 hover:bg-neutral-800/70 hover:text-white'
                      }`}
                      onMouseEnter={() => setSelectedIndex(index)}
                      onClick={() => goTo(result)}
                    >
                      <span>{result.label}</span>
                      <span className="text-xs text-neutral-500">{result.path}</span>
                    </button>
                  )
                }

                return (
                  <button
                    key={`model:${result.model.id}`}
                    type="button"
                    className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${
                      isSelected
                        ? 'bg-neutral-800 text-white'
                        : 'text-neutral-300 hover:bg-neutral-800/70 hover:text-white'
                    }`}
                    onMouseEnter={() => setSelectedIndex(index)}
                    onClick={() => goTo(result)}
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ backgroundColor: colorForDark(result.model.dev) }}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{result.model.name}</span>
                      <span className="block truncate text-xs text-neutral-500">{result.model.slug}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="rounded-md border border-neutral-800 bg-neutral-950 px-3 py-6 text-center text-sm text-neutral-500">
              No matches.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
