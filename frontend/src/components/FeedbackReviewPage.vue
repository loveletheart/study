<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ApiError,
  exportFeedback,
  feedbackError,
  getFeedback,
  listFeedback,
  reviewFeedback,
  updateFeedback,
} from '../api'
import type { FeedbackEdit, FeedbackRecord, FeedbackStatus } from '../types'
import { validateFeedbackEdit } from '../types'
import FeedbackFields from './FeedbackFields.vue'
import OutfitCard from './OutfitCard.vue'
const emit = defineEmits<{ close: []; logout: []; expired: [] }>()
const statuses: Record<FeedbackStatus, string> = {
  reported: '신고됨',
  draft: '초안',
  approved: '승인됨',
  rejected: '거절됨',
}
const status = ref<FeedbackStatus | ''>('')
const offset = ref(0)
const items = ref<FeedbackRecord[]>([])
const total = ref(0)
const selected = ref<FeedbackRecord | null>(null)
const originalWeather = computed<Record<string, unknown>>(() => {
  const weather = selected.value?.weather
  return weather && typeof weather === 'object' && !Array.isArray(weather)
    ? (weather as Record<string, unknown>)
    : {}
})
function weatherValue(key: string, unit: string): string {
  const value = originalWeather.value[key]
  return typeof value === 'number' && Number.isFinite(value) ? `${value}${unit}` : '정보 없음'
}
const draft = ref<FeedbackEdit>({ issues: [], note: '', corrected_day: null })
const comparison = ref<FeedbackRecord | null>(null)
const confirmed = ref(false)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const conflicted = ref(false)
let listController: AbortController | null = null
let detailController: AbortController | null = null
const lifetime = new AbortController()
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value))
const editOf = (r: FeedbackRecord): FeedbackEdit => ({
  issues: copy(r.issues),
  note: r.note,
  corrected_day: copy(r.corrected_day),
})
const dirty = computed(
  () => !!selected.value && JSON.stringify(draft.value) !== JSON.stringify(editOf(selected.value)),
)
function failure(cause: unknown) {
  error.value = feedbackError(cause)
  if (cause instanceof ApiError && cause.status === 409) conflicted.value = true
  if (cause instanceof ApiError && cause.status === 401) emit('expired')
}
async function loadList() {
  listController?.abort()
  const controller = new AbortController()
  listController = controller
  loading.value = true
  error.value = ''
  try {
    const result = await listFeedback(status.value, offset.value, controller.signal)
    if (!controller.signal.aborted) {
      items.value = result.items
      total.value = result.total
    }
  } catch (cause) {
    if (!controller.signal.aborted) failure(cause)
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}
function accept(record: FeedbackRecord) {
  selected.value = record
  draft.value = editOf(record)
  confirmed.value = false
  comparison.value = null
  conflicted.value = false
}
async function open(id: string) {
  if (
    busy.value ||
    (dirty.value && !window.confirm('저장하지 않은 수정 내용을 버리고 다른 항목을 열까요?'))
  )
    return
  detailController?.abort()
  const controller = new AbortController()
  detailController = controller
  selected.value = null
  comparison.value = null
  confirmed.value = false
  error.value = ''
  notice.value = ''
  try {
    const result = await getFeedback(id, controller.signal)
    if (!controller.signal.aborted) accept(result)
  } catch (cause) {
    if (!controller.signal.aborted) failure(cause)
  }
}
async function reloadForComparison() {
  if (!selected.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const latest = await getFeedback(selected.value.id, lifetime.signal)
    if (!lifetime.signal.aborted) {
      comparison.value = latest
      notice.value = '현재 입력은 유지했어요. 최신 기록을 확인하고 적용 방식을 선택해 주세요.'
    }
  } catch (cause) {
    if (!lifetime.signal.aborted) failure(cause)
  } finally {
    if (!lifetime.signal.aborted) busy.value = false
  }
}
function rebase(keep: boolean) {
  if (!comparison.value) return
  const edited = copy(draft.value)
  accept(comparison.value)
  if (keep) draft.value = edited
  notice.value = keep
    ? '최신 버전에 현재 입력을 적용했어요. 초안을 다시 저장해 주세요.'
    : '최신 기록을 불러왔어요.'
}
async function mutate(action: 'save' | 'approve' | 'reject') {
  const record = selected.value
  if (
    !record ||
    busy.value ||
    conflicted.value ||
    (action === 'approve' &&
      (dirty.value || !confirmed.value || !record.corrected_day || record.checks.errors.length))
  )
    return
  if (action === 'save') {
    error.value = validateFeedbackEdit(draft.value)
    if (error.value) return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result =
      action === 'save'
        ? await updateFeedback(
            record.id,
            { revision: record.revision, ...draft.value },
            lifetime.signal,
          )
        : await reviewFeedback(record.id, record.revision, action, lifetime.signal)
    if (!lifetime.signal.aborted) {
      accept(result)
      notice.value =
        action === 'save'
          ? '초안을 저장했어요. 기존 승인은 해제되며 별도 검수가 필요해요.'
          : action === 'approve'
            ? '내 수정안을 승인했어요.'
            : '내 수정안을 거절했어요.'
      void loadList()
    }
  } catch (cause) {
    if (!lifetime.signal.aborted) failure(cause)
  } finally {
    if (!lifetime.signal.aborted) busy.value = false
  }
}
function addCorrection() {
  if (selected.value?.original_day) draft.value.corrected_day = copy(selected.value.original_day)
}
async function download() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await exportFeedback(lifetime.signal)
    if (lifetime.signal.aborted) return
    const blob = new Blob(
      [
        result.records.map((record) => JSON.stringify(record)).join('\n') +
          (result.records.length ? '\n' : ''),
      ],
      { type: 'application/x-ndjson;charset=utf-8' },
    )
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'ondo-my-reviewed-feedback.jsonl'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    notice.value = `${result.count}개 내보내기 완료 · ${result.format}`
  } catch (cause) {
    if (!lifetime.signal.aborted) failure(cause)
  } finally {
    if (!lifetime.signal.aborted) busy.value = false
  }
}
watch(
  [status, offset],
  () => {
    void loadList()
  },
  { immediate: true },
)
watch(
  draft,
  () => {
    confirmed.value = false
  },
  { deep: true },
)
onBeforeUnmount(() => {
  lifetime.abort()
  listController?.abort()
  detailController?.abort()
  draft.value = { issues: [], note: '', corrected_day: null }
  items.value = []
  selected.value = null
  comparison.value = null
})
</script>

<template>
  <main class="feedback-review" aria-labelledby="review-title">
    <header class="feedback-actions">
      <h1 id="review-title">내 수정안 검수</h1>
      <button class="secondary-button" @click="emit('close')">옷차림으로 돌아가기</button
      ><button class="secondary-button" @click="emit('logout')">로그아웃</button>
    </header>
    <p>
      내 계정의 신고와 수정안만 확인해요. 초안 저장과 승인은 별개이며, 승인한 내 데이터만 내보낼 수
      있어요.
    </p>
    <div class="feedback-actions">
      <label
        >상태
        <select v-model="status" aria-label="상태" @change="offset = 0">
          <option value="">전체</option>
          <option v-for="(label, value) in statuses" :key="value" :value="value">
            {{ label }}
          </option>
        </select></label
      >
      <button class="secondary-button" :disabled="busy || loading" @click="loadList">
        목록 새로고침
      </button>
      <button class="primary-button" :disabled="busy" @click="download">
        내 승인 데이터 JSONL 내보내기
      </button>
    </div>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="loading" role="status">목록을 불러오는 중이에요.</p>
    <p v-else-if="!items.length">해당하는 내 신고가 없어요.</p>
    <ul class="feedback-list">
      <li v-for="item in items" :key="item.id">
        <button class="secondary-button" :disabled="busy" @click="open(item.id)">
          {{ item.date }} · {{ statuses[item.status] }} · {{ item.note || '설명 없음' }}
        </button>
      </li>
    </ul>
    <nav class="feedback-actions" aria-label="신고 목록 페이지">
      <button
        class="secondary-button"
        :disabled="offset === 0 || loading || busy"
        @click="offset = Math.max(0, offset - 20)"
      >
        이전</button
      ><span>{{ total }}건 · {{ Math.floor(offset / 20) + 1 }}페이지</span
      ><button
        class="secondary-button"
        :disabled="offset + 20 >= total || loading || busy"
        @click="offset += 20"
      >
        다음
      </button>
    </nav>
    <section v-if="selected" class="feedback-detail" aria-label="신고 상세">
      <h2>{{ selected.date }} · {{ statuses[selected.status] }}</h2>
      <p>
        수정 버전 {{ selected.revision }} · 검수 {{ selected.reviewer_kind || '미검수' }} ·
        {{ selected.reviewed_at || '미승인' }}
      </p>
      <section class="feedback-weather" aria-labelledby="original-weather-title">
        <h3 id="original-weather-title">원본 답변에 사용한 날씨</h3>
        <dl>
          <div>
            <dt>실제기온 최저~최고</dt>
            <dd>
              {{ weatherValue('temperature_min_c', '℃') }} ~
              {{ weatherValue('temperature_max_c', '℃') }}
            </dd>
          </div>
          <div>
            <dt>체감온도 최저~최고</dt>
            <dd>
              {{ weatherValue('apparent_temperature_min_c', '℃') }} ~
              {{ weatherValue('apparent_temperature_max_c', '℃') }}
            </dd>
          </div>
          <div>
            <dt>강수확률</dt>
            <dd>{{ weatherValue('precipitation_probability_percent', '%') }}</dd>
          </div>
          <div>
            <dt>강수량</dt>
            <dd>{{ weatherValue('precipitation_mm', 'mm') }}</dd>
          </div>
          <div>
            <dt>풍속</dt>
            <dd>{{ weatherValue('wind_speed_m_s', 'm/s') }}</dd>
          </div>
        </dl>
      </section>
      <details>
        <summary>서버 원본 날씨·취향·생성 정보</summary>
        <pre>{{
          JSON.stringify(
            {
              weather: selected.weather,
              preferences: selected.preferences,
              engine: selected.engine,
            },
            null,
            2,
          )
        }}</pre>
      </details>
      <details open>
        <summary>서버 원본 답변</summary>
        <template v-if="selected.original_day"
          ><OutfitCard
            :look="selected.original_day.best"
            :reasons="selected.original_day.reasons"
          /><OutfitCard
            :look="selected.original_day.worst"
            :reasons="selected.original_day.avoid_reasons"
            avoid
          />
          <p v-for="(note, index) in selected.original_day.precautions" :key="index">
            {{ note }}
          </p></template
        >
        <p v-else>서버 원본 답변이 없어요.</p>
      </details>
      <ul v-if="selected.checks.errors.length" role="alert">
        <li v-for="(check, index) in selected.checks.errors" :key="index">
          {{ check.message }}
        </li>
      </ul>
      <ul v-if="selected.checks.warnings.length">
        <li v-for="(check, index) in selected.checks.warnings" :key="index">
          {{ check.message }}
        </li>
      </ul>
      <form @submit.prevent="mutate('save')">
        <fieldset class="feedback-form" :disabled="busy">
          <legend>내 수정안</legend>
          <button
            v-if="!draft.corrected_day"
            type="button"
            class="secondary-button"
            :disabled="!selected.original_day"
            @click="addCorrection"
          >
            원본에서 수정안 작성
          </button>
          <button v-else type="button" class="secondary-button" @click="draft.corrected_day = null">
            수정안 제거
          </button>
          <FeedbackFields v-model="draft" />
        </fieldset>
        <p v-if="dirty">저장하지 않은 변경이 있어요. 승인 전에 초안을 저장해 주세요.</p>
        <div class="feedback-actions">
          <button class="primary-button" :disabled="busy || conflicted">
            초안 저장 (승인 해제)</button
          ><button
            type="button"
            class="secondary-button"
            :disabled="busy"
            @click="reloadForComparison"
          >
            최신 기록 다시 불러오기
          </button>
        </div>
      </form>
      <section v-if="comparison" aria-label="최신 기록 비교">
        <h3>최신 기록 · 버전 {{ comparison.revision }}</h3>
        <pre>{{ JSON.stringify(comparison, null, 2) }}</pre>
        <div class="feedback-actions">
          <button class="secondary-button" @click="rebase(true)">
            현재 입력을 최신 버전에 적용</button
          ><button class="secondary-button" @click="rebase(false)">
            현재 입력을 버리고 최신 기록 사용
          </button>
        </div>
      </section>
      <label class="feedback-confirm"
        ><input
          v-model="confirmed"
          type="checkbox"
          :disabled="
            busy ||
            dirty ||
            conflicted ||
            !selected.corrected_day ||
            !!selected.checks.errors.length
          "
        />내가 수정한 답변과 서버 검증 결과를 확인했으며 이 수정안을 승인합니다.</label
      >
      <div class="feedback-actions">
        <button
          class="primary-button"
          :disabled="
            busy ||
            dirty ||
            conflicted ||
            !confirmed ||
            !selected.corrected_day ||
            !!selected.checks.errors.length
          "
          @click="mutate('approve')"
        >
          내 수정안 승인</button
        ><button
          class="secondary-button"
          :disabled="busy || dirty || conflicted"
          @click="mutate('reject')"
        >
          내 수정안 거절
        </button>
      </div>
    </section>
  </main>
</template>
