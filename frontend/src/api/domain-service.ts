/**
 * 领域动作接口封装：批量情感分析、文本补录、重投与分布查询。
 * 与通用资源接口（backend-service.ts）区分，这里走 /api/domain 路由。
 */
import { request } from './client'

export type BlockReceipt = {
  block_id: string
  source_page?: string
  text_version?: string
  status: '已分析' | '待补录'
  found: boolean
  duplicate: boolean
  reason?: string
  supplement_id?: string
  记录ID?: string
  情感倾向?: string
  强烈程度?: string
  方面词?: string
  方面情感?: string
}

export type BatchDataset = {
  批次ID: string
  请求块数: number
  去重后块数: number
  已分析块数: number
  参与计数块数: number
  重复送达块数: number
  待补录块数: number
  覆盖页面: string[]
  覆盖页面数: number
  情感分布: Record<string, number>
  待补录块: string[]
  逐块回执: BlockReceipt[]
  delivered: boolean
}

export type BatchAnalyzeResult = {
  ok: boolean
  批次ID: string
  total_analyzed: number
  missing_count: number
  duplicate_count: number
  covered_pages: string[]
  sentiment_distribution: Record<string, number>
  block_receipts: BlockReceipt[]
  dataset: BatchDataset
}

export type SupplementItem = {
  补录ID: string
  块ID: string
  来源页面: string
  原批次ID: string
  关联批次: string[]
  文本版本: string
  状态: '待补录' | '已补录'
  登记原因: string
  块内容已找回?: boolean
  情感记录ID?: string
  交付批次ID?: string
}

export type SentimentSummary = {
  total_records: number
  counted_block_count: number
  sentiment_distribution: Record<string, number>
  intensity_distribution: Record<string, number>
  covered_pages: string[]
  covered_page_count: number
  pending_supplement_count: number
  pending_supplement_blocks: string[]
}

export type NegativeReviewBlock = BlockReceipt & { 批次ID: string }

async function domainCall<T>(
  module: string,
  action: string,
  args: unknown[] = [],
  kwargs: Record<string, unknown> = {},
): Promise<T> {
  const response = await request(`/api/domain/${module}/actions/${action}`, {
    method: 'POST',
    body: JSON.stringify({ args, kwargs }),
  })
  if (!response.ok) throw new Error(`领域动作 ${action} 请求失败`)
  const payload = await response.json()
  if (payload.ok === false) {
    throw new Error(payload.message ?? '领域动作执行失败')
  }
  return payload.data as T
}

// ------------------------------------------------------------ 文本分块
export function segmentPage(pageUrl: string) {
  return domainCall<{ ok: boolean; blocks: Record<string, unknown>[] }>(
    'text_segment', 'segment_page', [pageUrl],
  )
}

export function listSupplements(status?: string) {
  return domainCall<SupplementItem[]>('text_segment', 'list_supplements', [], {
    ...(status ? { status } : {}),
  })
}

export function restoreMissingBlock(
  supplementId: string,
  options: { source_page?: string; block_type?: string; text_sample?: string } = {},
) {
  return domainCall<{ ok: boolean; supplement: SupplementItem; block: Record<string, unknown> }>(
    'text_segment', 'restore_missing_block', [],
    { supplement_id: supplementId, ...options },
  )
}

// ------------------------------------------------------------ 情感标注
export function batchAnalyze(blockIds: string[], textVersions: Record<string, string> = {}) {
  return domainCall<BatchAnalyzeResult>('sentiment_tag', 'batch_analyze', [], {
    text_block_ids: blockIds,
    text_versions: textVersions,
  })
}

export function redeliverSupplement(supplementId: string) {
  return domainCall<BatchAnalyzeResult>('sentiment_tag', 'redeliver_supplement', [], {
    supplement_id: supplementId,
  })
}

export function listBatches() {
  return domainCall<BatchDataset[]>('sentiment_tag', 'list_batches')
}

export function getBatch(batchId: string) {
  return domainCall<BatchDataset>('sentiment_tag', 'get_batch', [], { batch_id: batchId })
}

export function negativeBlocksForReview(batchId?: string) {
  return domainCall<NegativeReviewBlock[]>('sentiment_tag', 'negative_blocks_for_review', [], {
    ...(batchId ? { batch_id: batchId } : {}),
  })
}

export function computeSentimentSummary() {
  return domainCall<SentimentSummary>('sentiment_tag', 'compute_sentiment_summary')
}
