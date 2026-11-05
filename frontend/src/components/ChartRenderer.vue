<script setup lang="ts">
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { ChartSpec } from '../api/types'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = withDefaults(
  defineProps<{
    spec: ChartSpec
    compact?: boolean
    clickable?: boolean
  }>(),
  { compact: false, clickable: false },
)

const emit = defineEmits<{ 'item-click': [name: string] }>()

const el = ref<HTMLDivElement | null>(null)

let chart: ECharts | null = null
let observer: ResizeObserver | null = null

const palette = ['#0f9d8a', '#5b5bd6', '#f59e0b', '#0ea5e9', '#e11d48', '#8b5cf6']

function buildOption(spec: ChartSpec): Record<string, unknown> {
  const base = {
    color: palette,
    animationDuration: 480,
    textStyle: {
      fontFamily: 'Inter, "Segoe UI", "PingFang SC", sans-serif',
      color: '#334155',
    },
  }

  if (spec.type === 'pie') {
    return {
      ...base,
      tooltip: {
        trigger: 'item',
        formatter: (params: { name?: string; value?: number }) =>
          `${params.name ?? ''}：${params.value ?? 0}${spec.unit ?? ''}`,
      },
      legend: {
        bottom: 0,
        icon: 'circle',
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { color: '#64748b', fontSize: 11 },
      },
      series: [
        {
          type: 'pie',
          radius: ['44%', '66%'],
          center: ['50%', '43%'],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
          label: { show: false },
          emphasis: {
            label: {
              show: true,
              color: '#0f172a',
              fontSize: 12,
              fontWeight: 600,
              formatter: '{b}\n{d}%',
            },
          },
          data: spec.data ?? [],
        },
      ],
    }
  }

  return {
    ...base,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: spec.type === 'bar' ? 'shadow' : 'line' },
      valueFormatter: (value: unknown) => `${value}${spec.unit ?? ''}`,
    },
    grid: { left: 10, right: 16, top: 26, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      data: spec.x ?? [],
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: {
        color: '#94a3b8',
        fontSize: 10,
        interval: 0,
        rotate: (spec.x?.length ?? 0) > 8 ? 30 : 0,
      },
    },
    yAxis: {
      type: 'value',
      name: spec.unit,
      nameTextStyle: { color: '#94a3b8', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f1f5f9' } },
      axisLabel: { color: '#94a3b8', fontSize: 10 },
    },
    series: (spec.series ?? []).map((item) => ({
      name: item.name,
      type: spec.type,
      data: item.data,
      smooth: spec.type === 'line',
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 2.4 },
      areaStyle: spec.type === 'line' ? { opacity: 0.08 } : undefined,
      barMaxWidth: 36,
      itemStyle: spec.type === 'bar' ? { borderRadius: [5, 5, 0, 0] } : undefined,
    })),
  }
}

function render() {
  chart?.setOption(buildOption(props.spec) as unknown as EChartsCoreOption, true)
}

function onChartClick(params: { name?: string }) {
  if (!props.clickable) return
  const name = typeof params.name === 'string' ? params.name.trim() : ''
  if (name) emit('item-click', name)
}

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value)
  chart.on('click', onChartClick)
  render()

  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(el.value)
})

watch(() => props.spec, render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" class="chart-canvas" :class="{ compact, clickable }"></div>
</template>
