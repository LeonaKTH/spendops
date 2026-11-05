import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api } from '../api'
import type { Dataset } from '../api/types'

export const useDatasetStore = defineStore('datasets', () => {
  const datasets = ref<Dataset[]>([])
  const loading = ref(false)
  const error = ref('')
  const activeIds = ref<string[]>([])

  const activeDatasets = computed(() =>
    datasets.value.filter((item) => activeIds.value.includes(item.id)),
  )

  async function load() {
    loading.value = true
    error.value = ''
    try {
      datasets.value = await api.listDatasets()
      if (activeIds.value.length === 0) {
        activeIds.value = datasets.value.map((item) => item.id)
      } else {
        activeIds.value = activeIds.value.filter((id) =>
          datasets.value.some((item) => item.id === id),
        )
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File, force = false): Promise<Dataset> {
    const created = await api.uploadDataset(file, force)
    datasets.value = [created, ...datasets.value]
    activeIds.value = [created.id, ...activeIds.value]
    return created
  }

  async function remove(id: string) {
    await api.removeDataset(id)
    datasets.value = datasets.value.filter((item) => item.id !== id)
    activeIds.value = activeIds.value.filter((item) => item !== id)
  }

  function toggleActive(id: string) {
    activeIds.value = activeIds.value.includes(id)
      ? activeIds.value.filter((item) => item !== id)
      : [...activeIds.value, id]
  }

  return {
    datasets,
    loading,
    error,
    activeIds,
    activeDatasets,
    load,
    upload,
    remove,
    toggleActive,
  }
})
