<script setup lang="ts">
import { computed } from 'vue'

import type { TableResult } from '../api/types'

const props = withDefaults(
  defineProps<{
    result: TableResult
    maxRows?: number
    maxHeight?: string
  }>(),
  {
    maxRows: 20,
    maxHeight: '320px',
  },
)

const rows = computed(() => props.result.rows.slice(0, props.maxRows))

const numeric = computed(() =>
  props.result.columns.map((_, index) =>
    rows.value.every((row) => {
      const value = row[index]
      return value === '' || value === null || value === undefined || typeof value === 'number'
    }),
  ),
)

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value !== 'number') return String(value)
  if (!Number.isFinite(value)) return '—'
  if (Number.isInteger(value)) return value.toLocaleString('zh-CN')
  const abs = Math.abs(value)
  const digits = abs >= 100 ? 2 : abs >= 1 ? 3 : 4
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  })
}
</script>

<template>
  <div class="table-wrap" :style="{ maxHeight }">
    <table>
      <thead>
        <tr>
          <th
            v-for="(column, index) in result.columns"
            :key="`${column}-${index}`"
            :class="{ num: numeric[index] }"
          >
            {{ column }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, rowIndex) in rows" :key="rowIndex">
          <td
            v-for="(cell, cellIndex) in row"
            :key="cellIndex"
            :class="{ num: numeric[cellIndex] }"
          >
            {{ formatCell(cell) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
