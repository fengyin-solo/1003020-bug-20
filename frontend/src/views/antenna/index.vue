<template>
  <section class="page" data-module="antenna">
    <header class="page-head">
      <div>
        <h2>天馈系统管理</h2>
        <p class="page-desc">维护天馈设备，围绕天馈编号、天线类型、工作频段、所属站点做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出天馈系统清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="search">
      <label class="filter-item">
        <span>天馈编号</span>
        <input v-model="keyword" placeholder="按天馈编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>驻波比排序</span>
        <select v-model="sort">
          <option value="">不排序</option>
          <option value="vswr_asc">驻波比从低到高</option>
          <option value="vswr_desc">驻波比从高到低</option>
        </select>
      </label>
      <label class="filter-item filter-check">
        <input v-model="pendingOnly" type="checkbox" />
        <span>只看待调整</span>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['天馈编号'] ?? '—' }}</td>
          <td>{{ row['天线类型'] ?? '—' }}</td>
          <td>{{ row['工作频段'] ?? '—' }}</td>
          <td>{{ row['所属站点'] ?? '—' }}</td>
          <td>{{ row['挂高'] ?? '—' }}</td>
          <td>{{ row['方位角'] ?? '—' }}</td>
          <td :class="{ 'over-limit': isOverLimit(row) }">
            {{ row['驻波比'] ?? '—' }}
            <span v-if="isOverLimit(row)" class="tag tag-danger">越限</span>
          </td>
          <td>
            <span :class="['tag', statusTagClass(row.status)]">{{ row['天馈状态'] ?? row.status }}</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEdit(row)">编辑资料</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无符合条件的天馈记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条天馈记录，第 {{ page }} / {{ totalPages }} 页</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
        <select v-model.number="size" @change="search">
          <option :value="5">每页 5 条</option>
          <option :value="10">每页 10 条</option>
          <option :value="20">每页 20 条</option>
        </select>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="editing" class="modal-mask" @click.self="closeEdit">
      <div class="modal">
        <h3>编辑天馈资料 · {{ editing['天馈编号'] }}</h3>
        <p class="page-desc">仅修改资料字段；驻波比越限时状态流转仍按「驻波优先」规则拦截。</p>
        <label v-for="field in editableFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="editForm[field]" :placeholder="`请输入${field}`" />
        </label>
        <div class="modal-actions">
          <button class="btn primary" type="button" :disabled="saving" @click="saveEdit">保存</button>
          <button class="btn ghost" type="button" @click="closeEdit">取消</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/antenna'
const VSWR_LIMIT = 1.5
const columns = ['天馈编号', '天线类型', '工作频段', '所属站点', '挂高', '方位角', '驻波比', '天馈状态']
const editableFields = ['所属站点', '挂高', '方位角', '驻波比']
const actions = ['记录异常', '记录偏移', '安排调整']
const statuses = ['正常', '驻波异常', '下倾偏移', '已调整']

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(5)
const errorMessage = ref('')

const keyword = ref('')
const statusFilter = ref('')
const pendingOnly = ref(false)
const sort = ref('')

const stats = ref([
  { label: '正常天馈', value: 0 },
  { label: '驻波异常数', value: 0 },
  { label: '下倾偏移数', value: 0 },
  { label: '待调整', value: 0 },
  { label: '已调整', value: 0 },
])

const editing = ref<Row | null>(null)
const editForm = reactive<Record<string, string>>({})
const saving = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))

function isOverLimit(row: Row): boolean {
  const value = Number(row['驻波比'])
  return Number.isFinite(value) && value > VSWR_LIMIT
}

function statusTagClass(status: string | number | boolean | null | undefined): string {
  if (status === '驻波异常') return 'tag-danger'
  if (status === '下倾偏移') return 'tag-warn'
  if (status === '已调整') return 'tag-ok'
  return ''
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  if (pendingOnly.value) params.set('pending_only', 'true')
  if (sort.value) params.set('sort', sort.value)
  params.set('page', String(page.value))
  params.set('size', String(size.value))
  return params.toString()
}

async function reload() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}?${buildQuery()}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail ?? '天馈设备列表读取失败')
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '天馈设备列表读取失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats/summary`)
    if (!response.ok) return
    const data = (await response.json()) as Record<string, number>
    stats.value = [
      { label: '正常天馈', value: data['正常'] ?? 0 },
      { label: '驻波异常数', value: data['驻波异常'] ?? 0 },
      { label: '下倾偏移数', value: data['下倾偏移'] ?? 0 },
      { label: '待调整', value: data['待调整'] ?? 0 },
      { label: '已调整', value: data['已调整'] ?? 0 },
    ]
  } catch {
    // 统计失败不阻断列表，卡片保持原值即可
  }
}

function search() {
  page.value = 1
  void reload()
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  pendingOnly.value = false
  sort.value = ''
  page.value = 1
  void reload()
}

function changePage(target: number) {
  if (target < 1 || target > totalPages.value) return
  page.value = target
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? payload?.detail ?? '天馈系统动作未生效，请稍后重试')
    }
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '天馈系统操作失败'
  }
}

function openEdit(row: Row) {
  editing.value = row
  for (const field of editableFields) {
    const value = row[field]
    editForm[field] = value === null || value === undefined ? '' : String(value)
  }
}

function closeEdit() {
  editing.value = null
}

async function saveEdit() {
  if (!editing.value) return
  saving.value = true
  errorMessage.value = ''
  try {
    const values: Record<string, string> = {}
    for (const field of editableFields) {
      values[field] = editForm[field].trim()
    }
    const response = await request(`${ENDPOINT}/${editing.value.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? payload?.detail ?? '资料保存失败')
    }
    closeEdit()
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资料保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.filter-check {
  display: flex;
  align-items: center;
  gap: 4px;
}
.filter-check input {
  margin: 0;
}
.over-limit {
  color: #b42318;
  font-weight: 600;
}
.tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid var(--border);
}
.tag-danger {
  color: #b42318;
  border-color: #f0a8a0;
  background: #fef3f2;
}
.tag-warn {
  color: #b54708;
  border-color: #f5c796;
  background: #fffaeb;
}
.tag-ok {
  color: #067647;
  border-color: #9ad6b6;
  background: #ecfdf3;
}
.pager {
  display: flex;
  gap: 8px;
  align-items: center;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 420px;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3 {
  margin: 0 0 6px;
}
.modal .filter-item {
  margin-bottom: 10px;
}
.modal .filter-item input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
