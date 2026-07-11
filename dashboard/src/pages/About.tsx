import type { ReactNode } from 'react'


function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="rounded-lg border border-neutral-800 bg-neutral-900 p-5"><h2 className="text-sm font-semibold text-neutral-100">{title}</h2><div className="mt-3 space-y-3 text-sm leading-6 text-neutral-400">{children}</div></section>
}

export default function About() {
  return <div className="mx-auto max-w-4xl space-y-4">
    <header className="rounded-lg border border-neutral-800 bg-neutral-900 p-6">
      <div className="text-xs font-medium uppercase tracking-[0.18em] text-neutral-500">ModelDB case study</div>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-neutral-100">Making model claims inspectable over time</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-neutral-400">ModelDB turns fragmented model announcements, benchmark leaderboards, provider pricing, and open-weight artifacts into a provenance-backed SQLite database and a static analytical interface.</p>
      <div className="mt-4 flex flex-wrap gap-3 text-sm"><a className="text-neutral-200 underline decoration-neutral-600 underline-offset-4 hover:decoration-neutral-300" href="/">Explore the live database</a><a className="text-neutral-200 underline decoration-neutral-600 underline-offset-4 hover:decoration-neutral-300" href="/changes">View recorded changes</a></div>
    </header>

    <Section title="The problem"><p>Model comparisons often collapse distinct releases, provider endpoints, aliases, evaluation conditions, and pricing tiers into one row. That makes a headline easy to read but hard to audit. This project keeps those distinctions so a reader can trace a displayed fact back to the source snapshot that supplied it.</p></Section>
    <Section title="Architecture"><ol className="list-decimal space-y-2 pl-5"><li>Ingest source payloads as append-only snapshots.</li><li>Resolve source-specific identifiers into canonical model releases while retaining aliases and confidence.</li><li>Promote benchmark, capability, price, provider-surface, and artifact facts into SQLite with provenance and validity fields.</li><li>Extract typed static JSON for this React, Vite, and ECharts dashboard.</li></ol></Section>
    <Section title="Hard engineering problems"><p><strong className="text-neutral-200">Identity:</strong> a provider alias, a “latest” endpoint, a quantization, and a release are not interchangeable. The schema separates them. <strong className="text-neutral-200">Comparison:</strong> benchmark scores can depend on effort, tools, prompts, and reporting method; evaluation conditions travel with results. <strong className="text-neutral-200">Time:</strong> source snapshots, first sightings, validity windows, measured dates, and refreshes are stored rather than inferred from a dashboard render.</p></Section>
    <Section title="Invariants"><ul className="list-disc space-y-2 pl-5"><li>Raw source payloads are append-only snapshots.</li><li>Canonical identity is separate from source aliases; aliases are retained.</li><li>Prices, capabilities, benchmarks, artifacts, and provider surfaces carry source provenance.</li><li>Evaluation settings describe a result, not a new model.</li><li>Historical changes are derived from stored observations; this view does not manufacture a changelog.</li></ul></Section>
    <Section title="Stack and deployment"><p>The data spine is SQLite with Python ingestion and resolution workflows. The public client is React, TypeScript, Vite, Tailwind, and ECharts. Build extraction bakes database data into static JSON. The dashboard is served as a static site at <a className="text-neutral-200 underline" href="https://models.wolfie.gg">models.wolfie.gg</a>; deployment intentionally leaves server-owned data out of asset syncs so a stale local build cannot replace live refresh output.</p></Section>
    <Section title="Methodology and limits"><p>Coverage depends on accessible sources and successful entity resolution. A source refresh proves the capture time, not that every provider claim is independently verified. Benchmark values remain comparable only within their stated benchmark and recorded conditions. Not every category has enough historical observations to produce a faithful diff; the Changes view omits categories without a persisted before/after trail rather than guessing.</p></Section>
  </div>
}
