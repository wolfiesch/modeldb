export interface NavigationItem {
  to: string
  label: string
}

export const NAVIGATION: NavigationItem[] = [
  { to: '/', label: 'Overview' },
  { to: '/changes', label: 'Changes' },
  { to: '/models', label: 'Model Explorer' },
  { to: '/lineage', label: 'Lineage & identity' },
  { to: '/elo', label: 'Arena over time' },
  { to: '/race', label: 'Leaderboard race' },
  { to: '/efficiency', label: 'Speed vs Quality' },
  { to: '/benchmarks', label: 'Benchmarks' },
  { to: '/tps', label: 'TPS Streams' },
  { to: '/compare', label: 'Compare' },
  { to: '/timeline', label: 'Timeline' },
  { to: '/landscape', label: 'Landscape' },
  { to: '/about', label: 'About the project' },
]
