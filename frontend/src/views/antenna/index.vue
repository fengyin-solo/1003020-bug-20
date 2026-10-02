<template>
  <section class="page" data-module="antenna">
    <header class="page-head">
      <div>
        <h2>天馈系统管理</h2>
        <p class="page-desc">
          驻波比越限线 {{ vswrLimit }}：越限须先记录异常再安排调整；状态沿 正常 → 驻波异常 → 下倾偏移 → 已调整 流转，不回退。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记天馈设备</button>
        <button class="btn" type="button" @click="exportRows">导出天馈系统清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>天馈编号</span>
        <input v-model="filters.keyword" placeholder="按天馈编号检索" />
      </label>
      <label class="filter-item">
        <span>天馈状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>驻波比排序</span>
        <select v-model="filters.vswrOrder">
          <option value="">默认顺序</option>
          <option value="asc">驻波比从低到高</option>
          <option value="desc">驻波比从高到低</option>
        </select>
      </label>
      <label class="filter-item filter-check">
        <input v-model="filters.pendingOnly" type="checkbox" />
        <span>只看待调整名单</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p v-if="notice" class="notice-text">{{ notice }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>待调整</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.pending ? '待调整' : '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEdit(row)">详情/编辑</button>
            <button
              v-for="action in rowActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!rowActions(row).length" class="muted-text">已闭环</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无天馈系统数据，可先登记天馈设备</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条天馈系统记录</span>
      <div class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="turnPage(-1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button class="btn" type="button" :disabled="page >= pageCount" @click="turnPage(1)">下一页</button>
        <select v-model.number="size" @change="applyFilters">
          <option v-for="option in sizeOptions" :key="option" :value="option">每页 {{ option }} 条</option>
        </select>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="editing" class="dialog-mask" @click.self="closeDialogs">
      <div class="dialog">
        <h3>天馈设备详情 — {{ editing['天馈编号'] }}</h3>
        <p class="dialog-meta">
          当前状态：{{ editing['天馈状态'] }}（{{ editing.pending ? '待调整' : '不在待调整名单' }}）
        </p>
        <label v-for="field in editableFields" :key="field" class="dialog-field">
          <span>{{ field }}</span>
          <input v-model="editForm[field]" :placeholder="`请输入${field}`" />
        </label>
        <p v-if="dialogError" class="error-text">{{ dialogError }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="button" @click="saveEdit">保存修改</button>
          <button class="btn ghost" type="button" @click="closeDialogs">取消</button>
        </div>
      </div>
    </div>

    <div v-if="creating" class="dialog-mask" @click.self="closeDialogs">
      <div class="dialog">
        <h3>登记天馈设备</h3>
        <label v-for="field in createFields" :key="field" class="dialog-field">
          <span>{{ field }}<em v-if="requiredFields.includes(field)" class="required-mark">*</em></span>
          <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
        </label>
        <p v-if="dialogError" class="error-text">{{ dialogError }}</p>
        <div class="dialog-actions">
          <button class="btn primary" type="button" @click="saveCreate">确认登记</button>
          <button class="btn ghost" type="button" @click="closeDialogs">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | undefined>
type ActionResult = { ok: boolean; message: string; entry?: Row | null }

const ENDPOINT = '/api/antenna'
const columns = ['天馈编号', '天线类型', '工作频段', '所属站点', '挂高', '方位角', '驻波比', '天馈状态']
const statuses = ['正常', '驻波异常', '下倾偏移', '已调整']
const editableFields = ['天线类型', '工作频段', '所属站点', '挂高', '方位角', '驻波比']
const createFields = ['天馈编号', ...editableFields]
const requiredFields = ['天馈编号', '天线类型', '工作频段']
const sizeOptions = [5, 10, 20, 50]

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const vswrLimit = ref(1.5)
const stats = ref([
  { label: '正常天馈', value: 0 },
  { label: '驻波异常数', value: 0 },
  { label: '偏移天馈数', value: 0 },
  { label: '待调整数', value: 0 },
])
const errorMessage = ref('')
const notice = ref('')
const filters = ref({ keyword: '', status: '', vswrOrder: '', pendingOnly: false })

const editing = ref<Row | null>(null)
const editForm = ref<Record<string, string>>({})
const creating = ref(false)
const createForm = ref<Record<string, string>>({})
const dialogError = ref('')

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

function rowActions(row: Row): string[] {
  switch (row['天馈状态']) {
    case '正常':
      return ['记录异常', '记录偏移', '安排调整']
    case '驻波异常':
      return ['记录偏移', '安排调整']
    case '下倾偏移':
      return ['记录异常', '安排调整']
    default:
      return []
  }
}

function buildQuery(): string {
  const params = new URLSearchParams()
  const keyword = filters.value.keyword.trim()
  if (keyword) params.set('keyword', keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  if (filters.value.vswrOrder) {
    params.set('sort', '驻波比')
    params.set('order', filters.value.vswrOrder)
  }
  if (filters.value.pendingOnly) params.set('pending', 'true')
  params.set('page', String(page.value))
  params.set('size', String(size.value))
  return params.toString()
}

async function readResult(response: Response, fallback: string): Promise<ActionResult> {
  const payload = (await response.json().catch(() => null)) as ActionResult | { detail?: string } | null
  if (!response.ok) {
    const detail = payload && 'detail' in payload ? payload.detail : undefined
    throw new Error(detail ?? fallback)
  }
  return (payload as ActionResult | null) ?? { ok: false, message: fallback }
}

async function reload() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}?${buildQuery()}`)
    const payload = await readResult(response, '天馈设备列表读取失败')
    const pageData = payload as unknown as { items?: Row[]; total?: number }
    rows.value = pageData.items ?? []
    total.value = pageData.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '天馈系统列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    const payload = (await response.json()) as {
      by_status?: Record<string, number>
      pending?: number
      vswr_limit?: number
    }
    const byStatus = payload.by_status ?? {}
    stats.value = [
      { label: '正常天馈', value: byStatus['正常'] ?? 0 },
      { label: '驻波异常数', value: byStatus['驻波异常'] ?? 0 },
      { label: '偏移天馈数', value: byStatus['下倾偏移'] ?? 0 },
      { label: '待调整数', value: payload.pending ?? 0 },
    ]
    vswrLimit.value = payload.vswr_limit ?? 1.5
  } catch {
    // 统计卡片失败不挡列表，保持静默
  }
}

async function refreshAll() {
  await Promise.all([reload(), loadStats()])
}

function applyFilters() {
  page.value = 1
  void reload()
}

function resetFilters() {
  filters.value = { keyword: '', status: '', vswrOrder: '', pendingOnly: false }
  applyFilters()
}

function turnPage(delta: number) {
  const next = page.value + delta
  if (next < 1 || next > pageCount.value) return
  page.value = next
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  notice.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const result = await readResult(response, '天馈系统动作未生效，请稍后重试')
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    notice.value = result.message
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '天馈系统操作失败'
  }
}

async function openEdit(row: Row) {
  dialogError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('天馈设备详情读取失败')
    }
    const detail = (await response.json()) as Row
    editing.value = detail
    const form: Record<string, string> = {}
    for (const field of editableFields) {
      const value = detail[field]
      form[field] = value === null || value === undefined ? '' : String(value)
    }
    editForm.value = form
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '天馈设备详情读取失败'
  }
}

async function saveEdit() {
  if (!editing.value) return
  dialogError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${editing.value.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: { ...editForm.value } }),
    })
    const result = await readResult(response, '天馈设备保存失败')
    if (!result.ok) {
      dialogError.value = result.message
      return
    }
    notice.value = result.message
    closeDialogs()
    await refreshAll()
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '天馈设备保存失败'
  }
}

function openCreate() {
  dialogError.value = ''
  createForm.value = Object.fromEntries(createFields.map((field) => [field, '']))
  creating.value = true
}

async function saveCreate() {
  dialogError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value } }),
    })
    const result = await readResult(response, '天馈设备登记失败')
    if (!result.ok) {
      dialogError.value = result.message
      return
    }
    notice.value = result.message
    closeDialogs()
    await refreshAll()
  } catch (error) {
    dialogError.value = error instanceof Error ? error.message : '天馈设备登记失败'
  }
}

function closeDialogs() {
  editing.value = null
  creating.value = false
  dialogError.value = ''
}

onMounted(refreshAll)
</script>

<style scoped>
.notice-text {
  margin: 0 0 8px;
  color: #067647;
  font-size: 13px;
}

.muted-text {
  color: var(--muted);
  font-size: 12px;
}

.pager {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.dialog-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.dialog {
  background: #fff;
  border-radius: 10px;
  padding: 20px;
  width: 380px;
  max-height: 80vh;
  overflow: auto;
}

.dialog h3 {
  margin: 0 0 8px;
  font-size: 15px;
}

.dialog-meta {
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 12px;
}

.dialog-field {
  display: block;
  margin-bottom: 10px;
}

.dialog-field span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}

.dialog-field input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}

.required-mark {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}

.dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
