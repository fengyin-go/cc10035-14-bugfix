import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import SentimentDistributionView from '@/views/SentimentDistributionView.vue'
import TextSupplementView from '@/views/TextSupplementView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 领域专属工作台需排在通用模块动态路由之前，否则会被 :moduleKey 抢先匹配。
    {
      path: '/text_segment_workbench',
      name: 'text-segment-workbench',
      component: TextSupplementView,
    },
    {
      path: '/sentiment_distribution',
      name: 'sentiment-distribution',
      component: SentimentDistributionView,
    },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
