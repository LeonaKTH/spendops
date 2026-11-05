<script setup lang="ts">
import { onMounted, ref } from 'vue'

import type { DocumentItem } from '../../api/types'
import { useDocumentStore } from '../../stores/documents'

const documents = useDocumentStore()

const busyId = ref('')
const actionError = ref('')

async function removeDocument(document: DocumentItem) {
  const ok = window.confirm(`确定删除文档「${document.name}」吗？对应的检索切片也会被删除。`)
  if (!ok) return

  busyId.value = `document-${document.id}`
  actionError.value = ''
  try {
    await documents.remove(document.id)
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busyId.value = ''
  }
}

onMounted(() => {
  void documents.load()
})
</script>

<template>
  <div class="view-stack">
    <div class="view-toolbar">
      <p class="view-note">
        合同文档用于条款问答与引用；数据集请在「数据接入」页维护，删除操作会同步删除物理表。
      </p>
      <RouterLink to="/ingest" class="btn btn-primary btn-sm">上传文档</RouterLink>
    </div>

    <p v-if="actionError" class="inline-error">{{ actionError }}</p>

    <section class="card">
      <div class="card-head">
        <div>
          <h2 class="card-title">合同文档</h2>
          <p class="card-sub">共 {{ documents.documents.length }} 份</p>
        </div>
        <button
          class="btn btn-ghost btn-sm"
          type="button"
          :disabled="documents.loading"
          @click="documents.load"
        >
          刷新
        </button>
      </div>

      <div v-if="documents.loading" class="empty-state compact">
        <span class="spinner"></span>
      </div>
      <p v-else-if="documents.error" class="inline-error">{{ documents.error }}</p>
      <div v-else-if="documents.documents.length === 0" class="empty-state compact">
        <p class="empty-desc">还没有合同文档。</p>
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>页数</th>
              <th>切片</th>
              <th>上传时间</th>
              <th class="align-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="document in documents.documents" :key="document.id">
              <td>
                <strong>{{ document.name }}</strong>
                <span class="table-sub">{{ document.sourceFile }}</span>
              </td>
              <td><span class="tag">{{ document.docType.toUpperCase() }}</span></td>
              <td>{{ document.pageCount || '—' }}</td>
              <td>{{ document.chunkCount }}</td>
              <td>{{ document.createdAt.slice(0, 10) }}</td>
              <td class="align-right">
                <button
                  class="btn btn-danger btn-sm"
                  type="button"
                  :disabled="busyId === `document-${document.id}`"
                  @click="removeDocument(document)"
                >
                  {{ busyId === `document-${document.id}` ? '删除中…' : '删除' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
