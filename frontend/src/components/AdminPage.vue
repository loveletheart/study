<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, errorMessage, getAdminOverview } from '../api'
import type { AdminOverview } from '../types'

const props = defineProps<{ signedIn: boolean }>()
const emit = defineEmits<{ close: []; login: []; expired: [] }>()
const controller = new AbortController()
const loading = ref(true)
const overview = ref<AdminOverview | null>(null)
const accessDenied = ref(false)
const error = ref('')
const numberFormat = new Intl.NumberFormat('ko-KR')
const batchTimeFormat = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  hourCycle: 'h23',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})
const batchStatuses = new Map([
  ['running', '진행 중'],
  ['retry_wait', '재시도 대기'],
  ['stopped', '중단'],
  ['partial_failure', '일부 실패'],
  ['completed', '완료'],
])

async function loadOverview() {
  loading.value = true
  overview.value = null
  accessDenied.value = false
  error.value = ''
  try {
    overview.value = await getAdminOverview(controller.signal)
  } catch (cause) {
    if (controller.signal.aborted) return
    if (cause instanceof ApiError) {
      accessDenied.value = cause.status === 401 || cause.status === 403
      if (cause.status === 401 && props.signedIn) emit('expired')
    }
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
  }
}

onMounted(loadOverview)
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <main class="profile-page">
    <header class="profile-header">
      <a class="account-brand" href="#main-content" @click.prevent="emit('close')"
        >온도<span>°</span></a
      >
      <button type="button" class="secondary-button" @click="emit('close')">
        추천으로 돌아가기
      </button>
    </header>
    <section class="admin-dashboard panel">
      <p v-if="loading" role="status">운영 현황을 불러오는 중입니다.</p>
      <template v-else-if="overview">
        <div class="dashboard-heading">
          <h1>관리자 페이지</h1>
          <button type="button" class="secondary-button" @click="loadOverview">새로고침</button>
        </div>
        <div class="dashboard-grid">
          <section class="dashboard-card">
            <h2>가입 계정</h2>
            <p class="account-total">{{ numberFormat.format(overview.registered_accounts) }}개</p>
          </section>
          <section class="dashboard-card">
            <h2>추천 피드백</h2>
            <dl class="metrics">
              <div>
                <dt>신고 접수</dt>
                <dd>{{ numberFormat.format(overview.feedback.reported) }}건</dd>
              </div>
              <div>
                <dt>수정안 작성</dt>
                <dd>{{ numberFormat.format(overview.feedback.draft) }}건</dd>
              </div>
              <div>
                <dt>승인</dt>
                <dd>{{ numberFormat.format(overview.feedback.approved) }}건</dd>
              </div>
              <div>
                <dt>거절</dt>
                <dd>{{ numberFormat.format(overview.feedback.rejected) }}건</dd>
              </div>
            </dl>
          </section>
          <section class="dashboard-card" aria-labelledby="latest-weekly-batch">
            <h2 id="latest-weekly-batch">최근 주간 배치</h2>
            <template v-if="overview.weekly_batch">
              <p class="batch-status">
                <time :datetime="overview.weekly_batch.run_date">{{
                  overview.weekly_batch.run_date
                }}</time>
                <strong>{{
                  batchStatuses.get(overview.weekly_batch.status) ?? overview.weekly_batch.status
                }}</strong>
              </p>
              <dl class="metrics">
                <div>
                  <dt>대기</dt>
                  <dd>{{ numberFormat.format(overview.weekly_batch.pending) }}건</dd>
                </div>
                <div>
                  <dt>완료</dt>
                  <dd>{{ numberFormat.format(overview.weekly_batch.completed) }}건</dd>
                </div>
                <div>
                  <dt>실패</dt>
                  <dd>{{ numberFormat.format(overview.weekly_batch.failed) }}건</dd>
                </div>
              </dl>
            </template>
            <p v-else class="muted">주간 배치 실행 기록이 없습니다.</p>
          </section>
        </div>
        <section
          v-if="overview.weekly_batch_history?.length"
          class="batch-history"
          aria-labelledby="weekly-batch-history"
        >
          <div class="dashboard-heading">
            <h2 id="weekly-batch-history">최근 7개 주간 배치 실행 기록</h2>
            <span class="muted">한국 시간</span>
          </div>
          <ol class="batch-history-list" role="list">
            <li
              v-for="(entry, index) in overview.weekly_batch_history"
              :key="index"
              class="dashboard-card"
            >
              <div class="dashboard-heading">
                <time :datetime="entry.batch.run_date">{{ entry.batch.run_date }}</time>
                <strong>{{ batchStatuses.get(entry.batch.status) ?? entry.batch.status }}</strong>
              </div>
              <dl class="metrics">
                <div>
                  <dt>시작</dt>
                  <dd>
                    <time :datetime="entry.started_at">{{
                      batchTimeFormat.format(new Date(entry.started_at))
                    }}</time>
                  </dd>
                </div>
                <div>
                  <dt>종료</dt>
                  <dd>
                    <time v-if="entry.finished_at" :datetime="entry.finished_at">{{
                      batchTimeFormat.format(new Date(entry.finished_at))
                    }}</time>
                    <span v-else>—</span>
                  </dd>
                </div>
                <div>
                  <dt>대기</dt>
                  <dd>{{ numberFormat.format(entry.batch.pending) }}건</dd>
                </div>
                <div>
                  <dt>완료</dt>
                  <dd>{{ numberFormat.format(entry.batch.completed) }}건</dd>
                </div>
                <div>
                  <dt>실패</dt>
                  <dd>{{ numberFormat.format(entry.batch.failed) }}건</dd>
                </div>
              </dl>
            </li>
          </ol>
        </section>
      </template>
      <template v-else-if="accessDenied">
        <h1>관리자 페이지 접근 제한</h1>
        <p class="form-error" role="alert">{{ error }}</p>
        <button v-if="!signedIn" type="button" class="secondary-button" @click="emit('login')">
          로그인
        </button>
      </template>
      <template v-else>
        <h1>관리자 페이지</h1>
        <p class="form-error" role="alert">{{ error }}</p>
        <button type="button" class="secondary-button" @click="loadOverview">다시 시도</button>
      </template>
    </section>
  </main>
</template>

<style scoped>
.admin-dashboard {
  padding: clamp(16px, 4vw, 36px);
}

.dashboard-heading,
.batch-status,
.metrics div {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}

.dashboard-heading h1,
.dashboard-card h2 {
  margin: 0;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 210px), 1fr));
  gap: 16px;
  margin-top: 24px;
}

.batch-history {
  margin-top: 24px;
}

.batch-history h2 {
  margin: 0;
  font-size: 1rem;
}

.batch-history-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 256px), 1fr));
  gap: 16px;
  margin: 12px 0 0;
  padding: 0;
  list-style: none;
}

.dashboard-card {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 12px;
}

.dashboard-card h2 {
  font-size: 1rem;
}

.account-total {
  margin: 10px 0 0;
  font-size: 1.75rem;
  font-weight: 700;
}

.metrics {
  display: grid;
  gap: 6px;
  margin: 12px 0 0;
}

.metrics dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.batch-status {
  margin: 12px 0;
}
</style>
