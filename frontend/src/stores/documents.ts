import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '../api'
import type { DocumentItem } from '../api/types'

export const useDocumentStore = defineStore('documents', () => {
  const documents = ref<DocumentItem[]>([])
  const loading = ref(false)
  const error = ref('')

  const totalChunks = computed(() =>
    documents.value.reduce((total, item) => total + item.chunkCount, 0),
  )

  async function load() {
    loading.value = true
    error.value = ''
    try {
      documents.value = await api.listDocuments()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File): Promise<DocumentItem> {
    const created = await api.uploadDocument(file)
    documents.value = [created, ...documents.value]
    return created
  }

  async function remove(id: string) {
    await api.removeDocument(id)
    documents.value = documents.value.filter((item) => item.id !== id)
  }

  return { documents, loading, error, totalChunks, load, upload, remove }
})
