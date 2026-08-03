import { lazy, Suspense, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router'
import { loadMeta, useData } from './lib/data'
import { NAVIGATION } from './lib/navigation'
import CommandPalette from './components/CommandPalette'
import { ModelDrawerProvider } from './components/ModelDrawer'

const Overview = lazy(() => import('./pages/Overview'))
const ModelExplorer = lazy(() => import('./pages/ModelExplorer'))
const ModelDetail = lazy(() => import('./pages/ModelDetail'))
const EloOverTime = lazy(() => import('./pages/EloOverTime'))
const Benchmarks = lazy(() => import('./pages/Benchmarks'))
const TpsStreams = lazy(() => import('./pages/TpsStreams'))
const Landscape = lazy(() => import('./pages/Landscape'))
const Race = lazy(() => import('./pages/Race'))
const Compare = lazy(() => import('./pages/Compare'))
const Timeline = lazy(() => import('./pages/Timeline'))
const DevPage = lazy(() => import('./pages/DevPage'))
const QualityLatencyPrice = lazy(() => import('./pages/QualityLatencyPrice'))
const Changes = lazy(() => import('./pages/Changes'))
const Lineage = lazy(() => import('./pages/Lineage'))
const About = lazy(() => import('./pages/About'))


export default function App() {
  const { data: meta } = useData(loadMeta)
  const [navOpen, setNavOpen] = useState(false)
  return (
    <ModelDrawerProvider>
      <div className="flex h-full">
        {navOpen && (
          <div
            className="fixed inset-0 z-30 bg-black/60 md:hidden"
            onClick={() => setNavOpen(false)}
          />
        )}
        <aside
          className="fixed inset-y-0 z-40 flex w-52 shrink-0 flex-col border-r border-neutral-800 bg-neutral-950 p-4 transition-[left] md:static"
          style={{ left: navOpen ? 0 : '-13rem' }}
        >
          <div className="mb-6">
            <div className="text-lg font-bold text-neutral-100">modeldb</div>
            <div className="text-xs text-neutral-500">AI model landscape</div>
          </div>
          <nav className="flex flex-col gap-1">
            {NAVIGATION.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onClick={() => setNavOpen(false)}
                className={({ isActive }) =>
                  `rounded px-3 py-2 text-sm ${isActive
                    ? 'bg-neutral-800 font-medium text-white'
                    : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'
                  }`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="mt-auto pt-6 text-[11px] leading-4 text-neutral-600">
            {meta && (
              <>
                <div>{meta.counts.models} models</div>
                <div>data as of {meta.generatedAt.slice(0, 10)}</div>
              </>
            )}
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-neutral-800 bg-neutral-950 px-4 py-3 md:justify-between md:px-6">
            <button
              type="button"
              aria-label="Toggle navigation"
              className="rounded border border-neutral-800 px-2 py-1 text-sm text-neutral-300 md:hidden"
              onClick={() => setNavOpen((v) => !v)}
            >
              ☰
            </button>
            <div className="text-sm text-neutral-400">
              Interactive browser for <span className="text-neutral-200">modeldb.sqlite</span>
            </div>
            {meta && (
              <div className="hidden text-xs text-neutral-500 sm:block">
                {meta.counts.benchmarkResults.toLocaleString()} benchmark results ·{' '}
                {meta.counts.priceComponents.toLocaleString()} price points · data as of{' '}
                {meta.generatedAt.slice(0, 10)}
              </div>
            )}
          </header>
          <main className="min-h-0 flex-1 overflow-y-auto bg-neutral-950 p-4 md:p-6">
            <Suspense fallback={<div className="p-6 text-sm text-neutral-500">Loading…</div>}>
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/models" element={<ModelExplorer />} />
                <Route path="/models/:slug" element={<ModelDetail />} />
                <Route path="/changes" element={<Changes />} />
                <Route path="/lineage" element={<Lineage />} />
                <Route path="/elo" element={<EloOverTime />} />
                <Route path="/benchmarks" element={<Benchmarks />} />
                <Route path="/tps" element={<TpsStreams />} />
                <Route path="/landscape" element={<Landscape />} />
                <Route path="/race" element={<Race />} />
                <Route path="/compare" element={<Compare />} />
                <Route path="/timeline" element={<Timeline />} />
                <Route path="/devs/:dev" element={<DevPage />} />
                <Route path="/efficiency" element={<QualityLatencyPrice />} />
                <Route path="/about" element={<About />} />
                <Route
                  path="*"
                  element={<div className="text-neutral-400">Page not found.</div>}
                />
              </Routes>
            </Suspense>
          </main>
        </div>
        <CommandPalette />
      </div>
    </ModelDrawerProvider>
  )
}
