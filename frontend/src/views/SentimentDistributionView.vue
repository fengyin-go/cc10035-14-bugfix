<template>
  <section class="page" data-module="sentiment_distribution">
    <header class="page-head">
      <div>
        <h2>情感分布发布台</h2>
        <p class="page-desc">
          发布的分布只统计真实分析块：标明实际覆盖的页面与参与计数的块，待补录缺块单列且不计中性。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/text_segment_workbench">返回文本分块工作台</RouterLink>
        <button class="btn ghost" type="button" @click="reload">刷新分布</button>
      </div>
    </header>

    <!-- 覆盖范围摘要 -->
    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">参与计数块</span>
        <strong class="stat-value">{{ summary?.counted_block_count ?? '—' }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">实际覆盖页面</span>
        <strong class="stat-value">{{ summary?.covered_page_count ?? '—' }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待补录缺块（不计入分布）</span>
        <strong class="stat-value" :class="{ 'text-warn': (summary?.pending_supplement_count ?? 0) > 0 }">
          {{ summary?.pending_supplement_count ?? '—' }}
        </strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">情感记录总数</span>
        <strong class="stat-value">{{ summary?.total_records ?? '—' }}</strong>
      </article>
    </div>

    <article class="workbench-card">
      <h3>实际覆盖页面</h3>
      <p v-if="!summary?.covered_pages.length" class="empty-state">暂无已分析块。</p>
      <div v-else class="page-list">
        <span v-for="page in summary.covered_pages" :key="page" class="page-tag">{{ page }}</span>
      </div>
      <p v-if="summary?.pending_supplement_blocks.length" class="pending-line">
        待补录块（分布未计数，也未计作中性）：
        <span v-for="blockId in summary.pending_supplement_blocks" :key="blockId" class="block-warn">
          {{ blockId }}
        </span>
      </p>
    </article>

    <!-- 情感分布柱状图 -->
    <article class="workbench-card">
      <h3>已发布情感分布（仅参与计数块）</h3>
      <div class="analysis-chart" data-testid="sentiment-chart">
        <div
          v-for="item in distributionRows"
          :key="item.label"
          class="chart-col"
          :data-testid="`dist-${item.label}`"
        >
          <div class="bar-wrap">
            <div
              class="analysis-bar"
              :class="`bar-${item.label}`"
              :style="{ height: barHeight(item.value) }"
            >
              <span class="bar-count">{{ item.value }}</span>
            </div>
          </div>
          <span class="bar-label">{{ labelText(item.label) }}</span>
        </div>
      </div>
      <p class="coverage-note">
        分布各情感合计 {{ distributionTotal }}，与参与计数块 {{ summary?.counted_block_count ?? 0 }}
        一致；缺块不参与任何情感类别计数。
      </p>
    </article>

    <!-- 负向块复查入口 -->
    <article class="workbench-card">
      <div class="card-head">
        <h3>负向块复查清单（值班员入口）</h3>
        <button class="btn ghost" type="button" @click="loadNegatives">刷新复查清单</button>
      </div>
      <p v-if="!negatives.length" class="empty-state">
        当前没有可复查的负向块；待补录块不会出现在这里。
      </p>
      <table v-else class="data-table" data-testid="negative-table">
        <thead>
          <tr><th>块ID</th><th>来源页面</th><th>情感倾向</th><th>强烈程度</th><th>所属批次</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in negatives" :key="`${item['批次ID']}-${item.block_id}`">
            <td class="mono">{{ item.block_id }}</td>
            <td>{{ item.source_page ?? '—' }}</td>
            <td><span class="badge-negative">{{ item['情感倾向'] }}</span></td>
            <td>{{ item['强烈程度'] ?? '—' }}</td>
            <td class="mono">{{ item['批次ID'] }}</td>
          </tr>
        </tbody>
      </table>
    </article>

    <footer class="page-foot">
      <span v-if="message" :class="messageError ? 'error-text' : ''">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  computeSentimentSummary,
  negativeBlocksForReview,
  type NegativeReviewBlock,
  type SentimentSummary,
} from '@/api/domain-service'

const LABELS = ['positive', 'negative', 'neutral', 'mixed']
const LABEL_TEXT: Record<string, string> = {
  positive: '正向',
  negative: '负向',
  neutral: '中性',
  mixed: '混合',
}

const summary = ref<SentimentSummary | null>(null)
const negatives = ref<NegativeReviewBlock[]>([])
const message = ref('')
const messageError = ref(false)

const distributionRows = computed(() =>
  LABELS.map((label) => ({
    label,
    value: summary.value?.sentiment_distribution[label] ?? 0,
  })),
)
const distributionTotal = computed(() =>
  distributionRows.value.reduce((acc, item) => acc + item.value, 0),
)
const maxValue = computed(() => Math.max(1, ...distributionRows.value.map((item) => item.value)))

function labelText(label: string): string {
  return LABEL_TEXT[label] ?? label
}

function barHeight(value: number): string {
  return `${Math.round((value / maxValue.value) * 100)}%`
}

async function loadNegatives() {
  try {
    negatives.value = await negativeBlocksForReview()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '负向复查清单读取失败'
    messageError.value = true
  }
}

async function reload() {
  try {
    summary.value = await computeSentimentSummary()
    await loadNegatives()
    message.value = ''
  } catch (error) {
    message.value = error instanceof Error ? error.message : '情感分布读取失败'
    messageError.value = true
  }
}

onMounted(reload)
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
.page-list { display: flex; flex-wrap: wrap; gap: 8px; }
.page-tag {
  background: #eef4ff;
  color: var(--brand);
  border-radius: 4px;
  padding: 3px 10px;
  font-size: 12px;
}
.pending-line { margin-top: 10px; font-size: 13px; color: var(--muted); }
.block-warn {
  display: inline-block;
  background: #fef3c7;
  color: #b45309;
  border-radius: 4px;
  padding: 2px 8px;
  margin-right: 6px;
  font-family: monospace;
  font-size: 12px;
}
.analysis-chart { height: 200px; align-items: flex-end; gap: 24px; padding: 12px 24px 28px; }
.chart-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
.bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; justify-content: center; }
.analysis-bar {
  width: 70%;
  min-height: 4px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
}
.analysis-bar.bar-positive { background: #22c55e; }
.analysis-bar.bar-negative { background: #ef4444; }
.analysis-bar.bar-neutral { background: #94a3b8; }
.analysis-bar.bar-mixed { background: #f59e0b; }
.bar-count { color: #fff; font-size: 12px; padding-top: 4px; }
.bar-label { margin-top: 8px; font-size: 12px; color: var(--muted); }
.coverage-note { font-size: 12px; color: var(--muted); margin: 8px 0 0; }
.badge-negative { color: #b91c1c; background: #fee2e2; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.text-warn { color: #b45309; }
.mono { font-family: monospace; font-size: 12px; }
</style>
