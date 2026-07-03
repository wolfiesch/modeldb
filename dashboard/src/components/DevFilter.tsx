import { useState } from 'react'
import LabLogo from './LabLogo'
import { colorForDark } from '../lib/theme'

interface DevFilterProps {
  devs: string[]
  value: string | null
  onChange: (dev: string | null) => void
  topN?: number
}

export default function DevFilter({ devs, value, onChange, topN = 8 }: DevFilterProps) {
  const [expanded, setExpanded] = useState(false)
  const visibleDevs = expanded ? devs : devs.slice(0, topN)
  const hiddenCount = Math.max(devs.length - topN, 0)

  return (
    <div className="flex flex-wrap gap-1">
      <button
        onClick={() => onChange(null)}
        className={`rounded border px-2 py-1 text-xs ${
          value === null
            ? 'border-neutral-300 bg-neutral-800 text-white'
            : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
        }`}
      >
        All
      </button>
      {visibleDevs.map((d) => (
        <button
          key={d}
          onClick={() => onChange(value === d ? null : d)}
          className="rounded border px-2 py-1 text-xs"
          style={{
            borderColor: value === d ? colorForDark(d) : 'rgba(64,64,64,0.5)',
            backgroundColor: value === d ? 'rgba(64,64,64,0.3)' : undefined,
            color: value === d ? '#fff' : '#a3a3a3',
          }}
        >
          <LabLogo dev={d} size={12} showLabel labelClassName="max-w-20 truncate" />
        </button>
      ))}
      {hiddenCount > 0 && (
        <button
          onClick={() => setExpanded((current) => !current)}
          className="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-400 hover:border-neutral-500"
        >
          {expanded ? 'Show less' : `+${hiddenCount} more`}
        </button>
      )}
    </div>
  )
}
