import { NavLink, Route, Routes } from 'react-router'
import { loadMeta, useData } from './lib/data'
import Overview from './pages/Overview'
import ModelExplorer from './pages/ModelExplorer'
import ModelDetail from './pages/ModelDetail'
import EloOverTime from './pages/EloOverTime'
import Benchmarks from './pages/Benchmarks'
import TpsStreams from './pages/TpsStreams'
import Landscape from './pages/Landscape'
import Race from './pages/Race'
import Compare from './pages/Compare'
import Timeline from './pages/Timeline'
import DevPage from './pages/DevPage'
import Consensus from './pages/Consensus'
import QualityLatencyPrice from './pages/QualityLatencyPrice'
import CommandPalette from './components/CommandPalette'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/models', label: 'Model Explorer' },
  { to: '/elo', label: 'Arena over time' },
  { to: '/race', label: 'Leaderboard race' },
  { to: '/consensus', label: 'Consensus matrix' },
  { to: '/efficiency', label: 'Speed vs Quality' },
  { to: '/benchmarks', label: 'Benchmarks' },
  { to: '/tps', label: 'TPS Streams' },
  { to: '/compare', label: 'Compare' },
  { to: '/timeline', label: 'Timeline' },
  { to: '/landscape', label: 'Landscape' },
]

export default function App() {
  const { data: meta } = useData(loadMeta)
  return (
    <div className="flex h-full">
      <aside className="flex w-52 shrink-0 flex-col border-r border-neutral-800 bg-neutral-950 p-4">
        <div className="mb-6">
          <div className="text-lg font-bold text-neutral-100">modeldb</div>
          <div className="text-xs text-neutral-500">AI model landscape</div>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `rounded px-3 py-2 text-sm ${
                  isActive
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
        <header className="flex items-center justify-between border-b border-neutral-800 bg-neutral-950 px-6 py-3">
          <div className="text-sm text-neutral-400">
            Interactive browser for <span className="text-neutral-200">modeldb.sqlite</span>
          </div>
          {meta && (
            <div className="text-xs text-neutral-500">
              {meta.counts.benchmarkResults.toLocaleString()} benchmark results ·{' '}
              {meta.counts.priceComponents.toLocaleString()} price points · data as of{' '}
              {new Date(meta.generatedAt).toLocaleString()}
            </div>
          )}
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto bg-neutral-950 p-6">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/models" element={<ModelExplorer />} />
            <Route path="/models/:slug" element={<ModelDetail />} />
            <Route path="/elo" element={<EloOverTime />} />
            <Route path="/benchmarks" element={<Benchmarks />} />
            <Route path="/tps" element={<TpsStreams />} />
            <Route path="/landscape" element={<Landscape />} />
            <Route path="/race" element={<Race />} />
            <Route path="/compare" element={<Compare />} />
            <Route path="/timeline" element={<Timeline />} />
            <Route path="/devs/:dev" element={<DevPage />} />
            <Route path="/consensus" element={<Consensus />} />
            <Route path="/efficiency" element={<QualityLatencyPrice />} />
            <Route
              path="*"
              element={<div className="text-neutral-400">Page not found.</div>}
            />
          </Routes>
        </main>
      </div>
      <CommandPalette />
    </div>
  )
}
