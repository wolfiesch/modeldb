import { useEffect, useId, useRef, useState } from 'react'
import type { Benchmark, BenchmarkResult } from '../lib/data'
import { buildEvidenceRows } from '../lib/evidence'

type EvidenceInspectorProps = {
  benchmark: Benchmark
  result: BenchmarkResult
  label: string
}

export function EvidenceInspector({ benchmark, result, label }: EvidenceInspectorProps) {
  const [open, setOpen] = useState(false)
  const closeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const rows = buildEvidenceRows(benchmark, result)

  useEffect(() => {
    if (!open) return
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="font-medium text-neutral-100 underline decoration-neutral-600 underline-offset-4 hover:text-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-400"
        aria-label={`Inspect evidence for ${benchmark.name}: ${label}`}
      >
        {label}
      </button>
      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false)
          }}
        >
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-neutral-700 bg-neutral-950 p-5 shadow-2xl">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h2 id={titleId} className="text-base font-semibold text-neutral-100">
                  Score evidence
                </h2>
                <p className="mt-1 text-xs text-neutral-400">{benchmark.name}</p>
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={() => setOpen(false)}
                className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-300 hover:border-neutral-500 focus:outline-none focus:ring-2 focus:ring-cyan-400"
              >
                Close
              </button>
            </div>
            <dl className="grid grid-cols-[minmax(9rem,auto)_minmax(0,1fr)] gap-x-4 gap-y-2 text-xs">
              {rows.map(([field, value]) => (
                <div key={field} className="contents">
                  <dt className="text-neutral-500">{field}</dt>
                  <dd className="break-words text-neutral-200">
                    {field === 'Source URL' && value !== 'Unavailable' ? (
                      <a href={value} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                        {value}
                      </a>
                    ) : (
                      value
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      ) : null}
    </>
  )
}
