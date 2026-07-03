import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { ThroughputRow } from '../lib/throughput'
import { coinPlanForThroughput } from '../lib/throughput'
import { colorForDark } from '../lib/theme'

export interface ThroughputCoinCanvasProps {
  rows: ThroughputRow[]
}

export default function ThroughputCoinCanvas({ rows }: ThroughputCoinCanvasProps) {
  return (
    <div className="relative h-[620px] overflow-hidden rounded-[2rem] border border-amber-400/20 bg-[radial-gradient(circle_at_50%_0%,rgba(245,158,11,0.22),transparent_38%),linear-gradient(180deg,#17130b_0%,#050505_100%)] shadow-2xl shadow-amber-950/30">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(90deg,rgba(251,191,36,0.08)_1px,transparent_1px),linear-gradient(0deg,rgba(251,191,36,0.05)_1px,transparent_1px)] bg-[size:44px_44px] opacity-40" />
      <Canvas camera={{ position: [0, 3.2, 8], fov: 45 }}>
        <CameraTarget />
        <ambientLight intensity={0.8} />
        <directionalLight position={[0, 6, 5]} intensity={1.6} color="#ffe4a3" />
        <pointLight position={[-4, 2, 3]} intensity={14} color="#f59e0b" distance={10} />
        {rows.map((row, index) => (
          <CoinStream key={row.key} row={row} index={index} total={rows.length} />
        ))}
      </Canvas>
      <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-between px-6 py-5 text-[10px] uppercase tracking-[0.35em] text-amber-200/60">
        <span>Assay chamber</span>
        <span>{rows.length} active lanes</span>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black via-black/70 to-transparent" />
    </div>
  )
}

function CameraTarget() {
  const camera = useThree((state) => state.camera)
  useEffect(() => {
    camera.lookAt(0, 0, 0)
    camera.updateProjectionMatrix()
  }, [camera])
  return null
}

function CoinStream({ row, index, total }: { row: ThroughputRow; index: number; total: number }) {
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const color = colorForDark(row.dev)
  const plan = coinPlanForThroughput(row.tps)
  const seeds = useMemo(() => makeSeeds(row.key, plan.count), [plan.count, row.key])
  const x = (index - (total - 1) / 2) * 2.1
  const geometry = useMemo(() => new THREE.CylinderGeometry(0.16, 0.16, 0.035, 40), [])
  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#f7c948',
        metalness: 0.92,
        roughness: 0.24,
        emissive: '#f59e0b',
        emissiveIntensity: 0.35,
      }),
    [],
  )

  const updateInstances = (elapsed: number) => {
    const mesh = meshRef.current
    if (!mesh) return
    for (let i = 0; i < plan.count; i += 1) {
      const seed = seeds[i]
      const phase = seed.phase
      const y = 5 - (((elapsed * plan.fallSpeed + phase) % 1) * 9.5)
      dummy.position.set(x + seed.xJitter, y, seed.zJitter)
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
    updateInstances(0)
    return () => {
      geometry.dispose()
      material.dispose()
    }
  }, [geometry, material])

  useFrame(({ clock }) => {
    updateInstances(clock.elapsedTime)
  })

  return (
    <group>
      <pointLight position={[x, 2.4, 1.2]} intensity={5} color={color} distance={4} />
      <instancedMesh ref={meshRef} args={[geometry, material, plan.count]} frustumCulled={false} />
    </group>
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
