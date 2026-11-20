<template>
  <section class="page" data-module="text_segment_workbench">
    <header class="page-head">
      <div>
        <h2>文本分块工作台</h2>
        <p class="page-desc">
          页面切分后逐块送情感分析；未找到的块进入文本补录清单，补回原标识后引用原批次重新交付。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/sentiment_distribution">打开情感分布发布台</RouterLink>
      </div>
    </header>

    <!-- 区域一：页面切分 -->
    <article class="workbench-card">
      <h3>① 页面文本切分</h3>
      <form class="analysis-form" @submit.prevent="onSegment">
        <label>
          页面 URL
          <input v-model="pageUrl" data-testid="segment-url" placeholder="https://example.com/page" required />
        </label>
        <button class="btn primary" data-testid="segment-submit" type="submit">切分入库</button>
      </form>
      <table v-if="recentBlocks.length" class="data-table">
        <thead>
          <tr><th>块ID</th><th>来源页面</th><th>块类型</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="block in recentBlocks" :key="String(block.id)" :data-status="String(block.status)">
            <td>{{ block['块ID'] }}</td>
            <td>{{ block['来源页面'] }}</td>
            <td>{{ block['块类型'] }}</td>
            <td>
              <span :class="{ 'badge-warn': block.status === '待补录' }">{{ block.status }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </article>

    <!-- 区域二：批量送审 -->
    <article class="workbench-card">
      <h3>② 批量送入情感分析（逐块校验来源）</h3>
      <form class="analysis-form" @submit.prevent="onBatchAnalyze">
        <label class="grow">
          文本块ID（逗号或换行分隔，可同时提交多个页面的块）
          <textarea
            v-model="blockIdInput"
            data-testid="batch-block-ids"
            rows="3"
            placeholder="块ID1, 块ID2, 块ID3"
          ></textarea>
        </label>
        <button class="btn primary" data-testid="batch-submit" type="submit">批量分析</button>
      </form>

      <div v-if="lastBatch" class="batch-result" data-testid="batch-result">
        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">批次ID</span>
            <strong class="stat-value small">{{ lastBatch['批次ID'] }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">参与计数块</span>
            <strong class="stat-value">{{ lastBatch['参与计数块数'] }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">重复送达</span>
            <strong class="stat-value">{{ lastBatch['重复送达块数'] }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">待补录缺块</span>
            <strong class="stat-value" :class="{ 'text-warn': lastBatch['待补录块数'] }">
              {{ lastBatch['待补录块数'] }}
            </strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">交付状态</span>
            <strong class="stat-value small">{{ lastBatch.delivered ? '完整交付' : '部分待补录' }}</strong>
          </article>
        </div>
        <p class="coverage-line">
          实际覆盖页面（{{ lastBatch['覆盖页面数'] }}）：
          <span v-for="page in lastBatch['覆盖页面']" :key="page" class="page-tag">{{ page }}</span>
        </p>
        <table class="data-table">
          <thead>
            <tr><th>块ID</th><th>来源页面</th><th>校验结果</th><th>情感倾向</th><th>是否重复</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="receipt in lastBatch['逐块回执']"
              :key="receipt.block_id"
              :data-status="receipt.status"
              :class="{ 'row-missing': !receipt.found }"
            >
              <td>{{ receipt.block_id }}</td>
              <td>{{ receipt.source_page ?? '—' }}</td>
              <td>
                <span :class="receipt.found ? 'badge-ok' : 'badge-warn'">{{ receipt.status }}</span>
                <span v-if="receipt.reason" class="reason-text">（{{ receipt.reason }}）</span>
              </td>
              <td>{{ receipt['情感倾向'] ?? '—' }}</td>
              <td>{{ receipt.duplicate ? '重复送达·只计一次' : '首次分析' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>

    <!-- 区域三：文本补录清单 -->
    <article class="workbench-card">
      <div class="card-head">
        <h3>③ 文本补录清单（逐条找回缺块）</h3>
        <button class="btn ghost" type="button" @click="loadSupplements">刷新清单</button>
      </div>
      <p v-if="!supplements.length" class="empty-state">暂无补录项，所有送审块均已找到。</p>
      <table v-else class="data-table">
        <thead>
          <tr>
            <th>补录ID</th><th>原块标识</th><th>引用原批次</th><th>文本版本</th>
            <th>状态</th><th>补回来源页面</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in supplements" :key="item['补录ID']" :data-status="item['状态']">
            <td>{{ item['补录ID'] }}</td>
            <td>{{ item['块ID'] }}</td>
            <td>{{ item['原批次ID'] || '—' }}</td>
            <td class="mono">{{ item['文本版本'] || '—' }}</td>
            <td>
              <span :class="item['状态'] === '待补录' ? 'badge-warn' : 'badge-ok'">
                {{ item['状态'] }}
              </span>
            </td>
            <td>
              <input
                v-if="item['状态'] === '待补录'"
                v-model="restorePages[item['补录ID']]"
                :data-testid="`restore-page-${item['补录ID']}`"
                :placeholder="item['来源页面'] || '输入来源页面'"
              />
              <span v-else>{{ item['来源页面'] }}</span>
            </td>
            <td>
              <button
                v-if="item['状态'] === '待补录'"
                class="btn primary small"
                data-testid="restore-redeliver"
                type="button"
                :disabled="busyId === item['补录ID']"
                @click="onRestoreAndRedeliver(item)"
              >
                {{ busyId === item['补录ID'] ? '重投中…' : '补回原标识并重投' }}
              </button>
              <span v-else class="badge-ok">已交付（{{ item['情感记录ID'] || '已回写' }}）</span>
            </td>
          </tr>
        </tbody>
      </table>
    </article>

    <!-- 区域四：逐块情感批次数据集 -->
    <article class="workbench-card">
      <div class="card-head">
        <h3>④ 逐块情感批次数据集（覆盖范围对账）</h3>
        <button class="btn ghost" type="button" @click="loadBatches">刷新批次</button>
      </div>
      <table v-if="batches.length" class="data-table">
        <thead>
          <tr>
            <th>批次ID</th><th>请求块数</th><th>参与计数</th><th>重复送达</th>
            <th>待补录</th><th>覆盖页面</th><th>交付</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="batch['批次ID']">
            <td class="mono">{{ batch['批次ID'] }}</td>
            <td>{{ batch['请求块数'] }}</td>
            <td>{{ batch['参与计数块数'] }}</td>
            <td>{{ batch['重复送达块数'] }}</td>
            <td :class="{ 'text-warn': batch['待补录块数'] }">{{ batch['待补录块数'] }}</td>
            <td>
              <span v-for="page in batch['覆盖页面']" :key="page" class="page-tag">{{ page }}</span>
            </td>
            <td>
              <span :class="batch.delivered ? 'badge-ok' : 'badge-warn'">
                {{ batch.delivered ? '完整交付' : '部分待补录' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">暂无批次数据，先在区域②提交批量分析。</p>
    </article>

    <footer class="page-foot">
      <span v-if="message" :class="messageError ? 'error-text' : ''">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  batchAnalyze,
  listBatches,
  listSupplements,
  redeliverSupplement,
  restoreMissingBlock,
  segmentPage,
  type BatchDataset,
  type SupplementItem,
} from '@/api/domain-service'
import { listEntries } from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const pageUrl = ref('')
const blockIdInput = ref('')
const recentBlocks = ref<EntryRow[]>([])
const lastBatch = ref<BatchDataset | null>(null)
const supplements = ref<SupplementItem[]>([])
const batches = ref<BatchDataset[]>([])
const restorePages = reactive<Record<string, string>>({})
const busyId = ref('')
const message = ref('')
const messageError = ref(false)

function notify(text: string, isError = false) {
  message.value = text
  messageError.value = isError
}

function parseBlockIds(raw: string): string[] {
  return raw
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function onSegment() {
  try {
    const result = await segmentPage(pageUrl.value.trim())
    notify(`切分完成：${result.blocks.length} 个块已入库`)
    const payload = await listEntries('text_segment', {})
    recentBlocks.value = payload.items
    pageUrl.value = ''
  } catch (error) {
    notify(error instanceof Error ? error.message : '页面切分失败', true)
  }
}

async function onBatchAnalyze() {
  const ids = parseBlockIds(blockIdInput.value)
  if (!ids.length) {
    notify('请先输入至少一个文本块ID', true)
    return
  }
  try {
    const result = await batchAnalyze(ids)
    lastBatch.value = result.dataset
    notify(
      result.missing_count
        ? `批次 ${result['批次ID']}：${result.total_analyzed} 块已分析，${result.missing_count} 块待补录（缺块未计入中性）`
        : `批次 ${result['批次ID']}：${result.total_analyzed} 块全部分析完成`,
      result.missing_count > 0,
    )
    await Promise.all([loadSupplements(), loadBatches()])
  } catch (error) {
    notify(error instanceof Error ? error.message : '批量分析失败', true)
  }
}

async function onRestoreAndRedeliver(item: SupplementItem) {
  busyId.value = item['补录ID']
  try {
    await restoreMissingBlock(item['补录ID'], {
      source_page: restorePages[item['补录ID']] || item['来源页面'] || undefined,
    })
    const redelivered = await redeliverSupplement(item['补录ID'])
    notify(
      `缺块 ${item['块ID']} 已补回并引用原批次 ${redelivered['批次ID']} 重新交付`,
    )
    await Promise.all([loadSupplements(), loadBatches()])
    if (lastBatch.value && redelivered.dataset) {
      lastBatch.value = redelivered.dataset['批次ID'] === lastBatch.value['批次ID']
        ? redelivered.dataset
        : lastBatch.value
    }
  } catch (error) {
    notify(error instanceof Error ? error.message : '补录重投失败', true)
  } finally {
    busyId.value = ''
  }
}

async function loadSupplements() {
  try {
    supplements.value = await listSupplements()
  } catch (error) {
    notify(error instanceof Error ? error.message : '补录清单读取失败', true)
  }
}

async function loadBatches() {
  try {
    batches.value = await listBatches()
  } catch (error) {
    notify(error instanceof Error ? error.message : '批次数据集读取失败', true)
  }
}

onMounted(async () => {
  const payload = await listEntries('text_segment', {})
  recentBlocks.value = payload.items
  await Promise.all([loadSupplements(), loadBatches()])
})
</script>

<style scoped>
.workbench-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.workbench-card h3 { margin: 0 0 10px; font-size: 15px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.analysis-form .grow { flex: 1; min-width: 260px; }
textarea { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 8px; font-family: inherit; }
.batch-result { margin-top: 12px; }
.stat-value.small { font-size: 13px; word-break: break-all; }
.coverage-line { font-size: 13px; color: var(--muted); margin: 8px 0; }
.page-tag {
  display: inline-block;
  background: #eef4ff;
  color: var(--brand);
  border-radius: 4px;
  padding: 2px 8px;
  margin-right: 6px;
  font-size: 12px;
}
.row-missing { background: #fff7ed; }
.badge-ok { color: #15803d; background: #dcfce7; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.badge-warn { color: #b45309; background: #fef3c7; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.text-warn { color: #b45309; }
.reason-text { color: var(--muted); font-size: 12px; }
.mono { font-family: monospace; font-size: 12px; }
.btn.small { padding: 4px 8px; font-size: 12px; }
</style>
