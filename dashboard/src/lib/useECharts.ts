import { useCallback, useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, ScatterChart, BarChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  ToolboxComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption, ECharts } from 'echarts/core'

echarts.use([
  LineChart,
  ScatterChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  ToolboxComponent,
  CanvasRenderer,
])

// Chart container may mount/unmount across renders (loading branches), so the
// hook returns a CALLBACK ref: init runs whenever the node appears, dispose
// whenever it disappears.
export function useECharts(
  option: EChartsCoreOption | null,
  onClick?: (params: unknown) => void,
) {
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  const chartRef = useRef<ECharts | null>(null)
  const clickRef = useRef(onClick)
  clickRef.current = onClick

  const refCallback = useCallback((node: HTMLDivElement | null) => setEl(node), [])

  useEffect(() => {
    if (!el) return
    const chart = echarts.init(el, undefined, { renderer: 'canvas' })
    chartRef.current = chart
    chart.on('click', (params) => clickRef.current?.(params))
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(el)
    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [el])

  useEffect(() => {
    if (option && chartRef.current) {
      chartRef.current.setOption(option, { notMerge: true })
      // The container may have mounted at 0×0 (e.g. just after a loading
      // branch flips). Force a resize on the next frame so marks paint into
      // the real box instead of an empty canvas.
      const raf = requestAnimationFrame(() => chartRef.current?.resize())
      return () => cancelAnimationFrame(raf)
    }
  }, [option, el])

  return refCallback
}
