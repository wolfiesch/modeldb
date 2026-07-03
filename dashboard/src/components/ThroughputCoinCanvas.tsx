import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import type { ThroughputRow } from '../lib/throughput'
import { coinPlanForThroughput } from '../lib/throughput'
import { colorForDark } from '../lib/theme'

export interface ThroughputCoinCanvasProps {
  rows: ThroughputRow[]
  highlightKey?: string | null
  onLaneHover?: (key: string | null) => void
}

export default function ThroughputCoinCanvas({ rows, highlightKey = null, onLaneHover }: ThroughputCoinCanvasProps) {
  const [userPaused, setUserPaused] = useState(
    () =>
      typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  const [documentHidden, setDocumentHidden] = useState(
    () => typeof document !== 'undefined' && document.visibilityState === 'hidden',
  )
  const isPaused = userPaused || documentHidden
  const totalLanes = rows.length + 1

  useEffect(() => {
    if (typeof document === 'undefined') return
    const handleVisibilityChange = () => {
      setDocumentHidden(document.visibilityState === 'hidden')
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handleChange = () => {
      if (media.matches) setUserPaused(true)
    }
    media.addEventListener('change', handleChange)
    return () => {
      media.removeEventListener('change', handleChange)
    }
  }, [])

  return (
    <div className="relative h-[620px] overflow-hidden rounded-[2rem] border border-amber-400/20 bg-[radial-gradient(circle_at_50%_0%,rgba(245,158,11,0.22),transparent_38%),linear-gradient(180deg,#17130b_0%,#050505_100%)] shadow-2xl shadow-amber-950/30">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,rgba(251,191,36,0.08)_1px,transparent_1px),linear-gradient(0deg,rgba(251,191,36,0.05)_1px,transparent_1px)] bg-[size:44px_44px] opacity-40" />
      <Canvas camera={{ position: [0, 0, 8], fov: 45 }} dpr={[1, 2]} frameloop={isPaused ? 'demand' : 'always'}>
        <ambientLight intensity={0.8} />
        <directionalLight position={[0, 6, 5]} intensity={1.6} color="#ffe4a3" />
        <pointLight position={[-4, 2, 3]} intensity={14} color="#f59e0b" distance={10} />
        <CoinStream streamKey="reference:100-tps" tps={100} dev={null} index={0} total={totalLanes} isPaused={isPaused} ghost />
        {rows.map((row, index) => (
          <CoinStream
            key={row.key}
            streamKey={row.key}
            tps={row.tps}
            dev={row.dev}
            index={index + 1}
            total={totalLanes}
            isPaused={isPaused}
            dimmed={highlightKey !== null && highlightKey !== row.key}
          />
        ))}
      </Canvas>
      <div className="pointer-events-none absolute inset-x-0 top-0 z-30 flex justify-between px-6 py-5 text-[10px] uppercase tracking-[0.35em] text-amber-200/60">
        <span>Assay chamber</span>
        <span>{rows.length} active lanes</span>
      </div>
      <button
        type="button"
        aria-pressed={userPaused}
        onClick={() => setUserPaused((paused) => !paused)}
        className="pointer-events-auto absolute right-4 top-4 z-40 rounded-full border border-amber-300/30 bg-black/60 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.2em] text-amber-100 shadow-lg shadow-black/40 backdrop-blur transition hover:border-amber-200/70 hover:text-white"
      >
        {isPaused ? 'Play' : 'Pause'}
      </button>
      <div
        className="pointer-events-auto absolute inset-x-0 top-14 bottom-0 z-20 flex"
        onPointerLeave={() => onLaneHover?.(null)}
      >
        <div className="h-full flex-1" onPointerEnter={() => onLaneHover?.(null)} />
        {rows.map((row) => (
          <div key={row.key} className="h-full flex-1" onPointerEnter={() => onLaneHover?.(row.key)} />
        ))}
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-28 bg-gradient-to-t from-black via-black/70 to-transparent" />
      <div className="pointer-events-none absolute inset-x-0 bottom-3 z-30 flex gap-1 px-1 sm:gap-1.5 sm:px-1.5">
        <LaneLabel label="100 TPS reference" tps={100} color="#9ca3af" muted />
        {rows.map((row, index) => (
          <LaneLabel
            key={row.key}
            rank={index + 1}
            label={row.modelName}
            tps={row.tps}
            color={colorForDark(row.dev)}
            highlighted={highlightKey === row.key}
          />
        ))}
      </div>
    </div>
  )
}

function CoinStream({
  streamKey,
  tps,
  dev,
  index,
  total,
  isPaused,
  dimmed = false,
  ghost = false,
}: {
  streamKey: string
  tps: number
  dev: string | null
  index: number
  total: number
  isPaused: boolean
  dimmed?: boolean
  ghost?: boolean
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const elapsedRef = useRef(0)
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const color = ghost ? '#9ca3af' : colorForDark(dev)
  const plan = coinPlanForThroughput(tps)
  const seeds = useMemo(() => makeSeeds(streamKey, plan.count), [plan.count, streamKey])
  const viewport = useThree((state) => state.viewport)
  const invalidate = useThree((state) => state.invalidate)
  // Lane centers match the equal-width HTML label cells: viewport-fraction spacing
  // instead of a fixed world-unit pitch, so labels line up with their streams.
  const pitch = viewport.width / total
  const x = (index + 0.5) * pitch - viewport.width / 2
  const fallTop = viewport.height / 2 + 0.8
  const fallTravel = viewport.height + 1.6

  const updateInstances = (elapsed: number) => {
    const mesh = meshRef.current
    if (!mesh) return
    mesh.count = plan.count
    for (let i = 0; i < plan.count; i += 1) {
      const seed = seeds[i]
      const sway = Math.sin(elapsed * (0.4 + seed.spin) + seed.phase * Math.PI * 2) * pitch * 0.06
      const y = fallTop - (((elapsed * plan.fallSpeed + seed.phase) % 1) * fallTravel)
      dummy.position.set(x + seed.xJitter * pitch * 0.78 + sway, y, seed.zJitter)
      dummy.rotation.set(elapsed * (0.7 + seed.spin), seed.tilt + elapsed * seed.spin, seed.roll)
      const scale = 0.76 + seed.scale * 0.56
      dummy.scale.setScalar(scale)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
    }
    mesh.instanceMatrix.needsUpdate = true
  }

  useEffect(() => {
    meshRef.current?.instanceMatrix.setUsage(THREE.DynamicDrawUsage)
    updateInstances(elapsedRef.current)
    invalidate()
  })

  useFrame((_state, delta) => {
    if (!isPaused) elapsedRef.current += delta
    updateInstances(elapsedRef.current)
  })

  return (
    <group>
      <pointLight position={[x, 2.4, 1.2]} intensity={ghost ? 1.6 : dimmed ? 1.8 : 5} color={color} distance={4} />
      <instancedMesh key={plan.count} ref={meshRef} args={[undefined, undefined, plan.count]} frustumCulled={false}>
        <cylinderGeometry args={[0.16, 0.16, 0.035, 40]} />
        <meshStandardMaterial
          color={ghost ? '#9ca3af' : '#f7c948'}
          metalness={ghost ? 0.45 : 0.92}
          roughness={ghost ? 0.5 : 0.24}
          emissive={ghost ? '#64748b' : '#f59e0b'}
          emissiveIntensity={ghost ? 0.08 : dimmed ? 0.12 : 0.35}
          transparent
          opacity={ghost ? 0.35 : dimmed ? 0.25 : 1}
        />
      </instancedMesh>
    </group>
  )
}

function LaneLabel({
  rank,
  label,
  tps,
  color,
  highlighted = false,
  muted = false,
}: {
  rank?: number
  label: string
  tps: number
  color: string
  highlighted?: boolean
  muted?: boolean
}) {
  return (
    <div
      className={`min-w-0 flex-1 rounded-2xl border px-2 py-2 text-left backdrop-blur sm:px-3 ${
        highlighted
          ? 'border-amber-200/80 bg-amber-300/15 text-amber-50 shadow-[0_0_28px_rgba(251,191,36,0.35)]'
          : muted
            ? 'border-slate-300/15 bg-slate-950/45 text-slate-300/75'
            : 'border-amber-300/15 bg-black/40 text-amber-100/80'
      }`}
      style={{ boxShadow: highlighted ? `0 0 0 1px ${color}` : undefined }}
    >
      <div className="flex min-w-0 items-center gap-1.5 sm:gap-2">
        {rank ? (
          <span
            className="grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-black text-black"
            style={{ backgroundColor: color }}
          >
            {rank}
          </span>
        ) : null}
        <span className="truncate text-[10px] font-semibold leading-tight sm:text-xs">{label}</span>
      </div>
      <div className="mt-1 truncate text-[9px] font-bold uppercase tracking-[0.18em] text-amber-200/70 sm:text-[10px]">
        {tps.toFixed(0)} TPS
      </div>
    </div>
  )
}

interface CoinSeed {
  phase: number
  xJitter: number
  zJitter: number
  spin: number
  tilt: number
  roll: number
  scale: number
}

function makeSeeds(key: string, count: number): CoinSeed[] {
  let state = hashString(key)
  return Array.from({ length: count }, () => {
    state = nextState(state)
    const phase = state / 0xffffffff
    state = nextState(state)
    const xJitter = (state / 0xffffffff - 0.5) * 0.9
    state = nextState(state)
    const zJitter = (state / 0xffffffff - 0.5) * 1.2
    state = nextState(state)
    const spin = state / 0xffffffff
    state = nextState(state)
    const tilt = (state / 0xffffffff) * Math.PI
    state = nextState(state)
    const roll = (state / 0xffffffff) * Math.PI
    state = nextState(state)
    const scale = state / 0xffffffff
    return { phase, xJitter, zJitter, spin, tilt, roll, scale }
  })
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function nextState(value: number): number {
  return (Math.imul(value, 1664525) + 1013904223) >>> 0
}
