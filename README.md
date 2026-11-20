# Web语义抽取与内容理解中心

面向Web结构化数据采集场景，提供页面DOM解析、实体识别、关系抽取、内容分类和知识图谱构建的语义抽取平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| DOM解析 | `dom_parser` | 解析配置 | 配置名称、目标URI、解析引擎 |
| 实体抽取 | `entity_extract` | 实体条目 | 实体ID、实体类型、实体名称 |
| 关系图谱 | `relation_graph` | 关系边 | 边ID、源实体、目标实体 |
| 内容分类 | `content_classifier` | 分类标签 | 标签ID、页面URI、一级分类 |
| 模板规则 | `template_rule` | 规则模板 | 模板名称、适用站点、提取字段 |
| 文本分块 | `text_segment` | 文本块 | 块ID、来源页面、块类型 |
| 情感标注 | `sentiment_tag` | 情感记录 | 记录ID、文本片段、情感倾向 |
| Schema对齐 | `schema_align` | 对齐规则 | 规则名称、源Schema、目标Schema |
| 种子调度 | `feed_scheduler` | 调度任务 | 任务名称、URL种子、抓取深度 |
| 质量检查 | `quality_check` | 检查规则 | 规则名称、检查字段、检查类型 |
| 探针选择 | `probe_selector` | 探针配置 | 探针名称、目标页面、选择器列表 |
| 页面快照 | `page_snapshot` | 快照记录 | 快照ID、页面URI、DOM哈希 |
| 抽取指标 | `extract_metric` | 指标记录 | 记录时间、所属任务、成功页面数 |
| 语义结果 | `nlu_result` | 语义记录 | 记录ID、输入文本、意图标签 |
| 知识链接 | `knowledge_link` | 链接记录 | 链接ID、源实体、外部URI |
| 输出目标 | `output_target` | 输出配置 | 配置名称、输出类型、目标地址 |
| 抽取工坊 | `extract_studio` | 交互任务 | 任务名称、示例页面、标注区域 |
| 聚合视图 | `aggregate_view` | 视图配置 | 视图名称、统计维度、聚合字段 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 缺块回执与文本补录（文本分块 × 情感标注）

批量情感分析对每个送入的文本块逐块校验来源，缺块不再被静默丢弃：

- `POST /api/domain/sentiment_tag/actions/batch_analyze`
  交付「逐块情感批次数据集」：逐块回执（已分析/待补录）、实际覆盖页面、
  参与计数块、重复送达块、待补录块与完整四类情感分布。缺块单列，绝不计入中性。
- 未找到的块自动登记到文本补录清单（`text_supplement` 表），并在分块表留
  `待补录` 占位；占位块不参与正常分块统计，也不会被情感分析当成真实块。
- 幂等：按 `块ID + 文本版本` 去重，同一文本版本重复送达分布只算一次，
  中断重试可凭该键区分「已分析」与「待补录」。
- 工作台流程：`text_segment/restore_missing_block` 补回原块标识与内容 →
  `sentiment_tag/redeliver_supplement` 引用原批次重新交付，回执原地并回原批次
  数据集（不产生重复批次），补录清单回写为「已补录」。
- `sentiment_tag/negative_blocks_for_review` 提供值班员负向块复查入口，
  只含真实分析块；`compute_sentiment_summary` 与聚合视图标明覆盖页面、
  参与计数块和待补录块，发布统计与补录清单覆盖范围始终对得上。

### 领域工作台页面

| 路由 | 视图 | 能力 |
| --- | --- | --- |
| `/text_segment_workbench` | `TextSupplementView.vue` | 页面切分、批量送审、补录清单逐条补回重投、批次数据集对账 |
| `/sentiment_distribution` | `SentimentDistributionView.vue` | 已发布情感分布（覆盖页面/参与计数块）、待补录块、负向块复查 |

### 验证脚本

```bash
# 服务层端到端（直接调用领域服务，无需起服务）
cd backend && .venv/bin/python -I ../tests/integration_scenario.py
# HTTP 接口层（需先启动后端，默认读 http://127.0.0.1:8016，可改脚本内 BASE）
.venv/bin/python -I ../tests/http_scenario.py
```

领域：数据工程
子方向：数据采集、爬虫与RPA
