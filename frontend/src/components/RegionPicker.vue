<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { errorMessage, searchLocations } from '../api'
import { locationLabel } from '../utils'
import type { Location } from '../types'
import AppIcon from './AppIcon.vue'
defineProps<{ busy?: boolean; saveError?: string }>()

const emit = defineEmits<{ close: []; select: [location: Location] }>()
const dialog = ref<HTMLDialogElement>()
const input = ref<HTMLInputElement>()
const query = ref('')
const locations = ref<Location[]>([])
const loading = ref(false)
const error = ref('')
const searched = ref(false)
const attribution = ref('')
const total = ref(0)
const hasMore = ref(false)
let revision = 0
let debounce: ReturnType<typeof setTimeout> | undefined
let current: AbortController | undefined

async function search(more = false) {
  if (more && (loading.value || !hasMore.value)) return
  clearTimeout(debounce)
  current?.abort()
  const value = query.value.trim()
  if (value.length < 2) return
  const requestRevision = ++revision
  const offset = more ? locations.value.length : 0
  if (!more) {
    locations.value = []
    total.value = 0
    hasMore.value = false
  }
  const controller = new AbortController()
  current = controller
  loading.value = true
  error.value = ''
  searched.value = true
  try {
    const result = await searchLocations(value, controller.signal, offset)
    if (revision === requestRevision && !controller.signal.aborted) {
      locations.value = more ? [...locations.value, ...result.locations] : result.locations
      total.value = result.total ?? locations.value.length
      hasMore.value = result.has_more ?? false
      attribution.value = result.attribution
    }
  } catch (cause) {
    if (revision === requestRevision && !controller.signal.aborted)
      error.value = errorMessage(cause)
  } finally {
    if (current === controller) loading.value = false
  }
}

watch(query, () => {
  revision++
  current?.abort()
  clearTimeout(debounce)
  locations.value = []
  total.value = 0
  hasMore.value = false
  loading.value = false
  searched.value = false
  error.value = ''
  if (query.value.trim().length >= 2)
    debounce = setTimeout(() => {
      void search()
    }, 350)
})
onMounted(async () => {
  dialog.value?.showModal()
  await nextTick()
  input.value?.focus()
})
onBeforeUnmount(() => {
  current?.abort()
  clearTimeout(debounce)
})
</script>

<template>
  <dialog
    ref="dialog"
    class="modal region-modal"
    aria-labelledby="region-title"
    @cancel.prevent="emit('close')"
    @click="
      (event) => {
        if (event.target === dialog) emit('close')
      }
    "
  >
    <div class="modal-heading">
      <div>
        <p class="eyebrow">MY NEIGHBORHOOD</p>
        <h2 id="region-title">어디의 날씨가 궁금하세요?</h2>
      </div>
      <button class="icon-button" aria-label="지역 선택 닫기" @click="emit('close')">
        <AppIcon name="close" />
      </button>
    </div>
    <p class="muted">지역명 일부로 찾아보세요. 서울 강남처럼 함께 입력하면 더 좁혀볼 수 있어요.</p>
    <p v-if="busy" class="loading-line" role="status">
      <span class="spinner" />지역을 계정에 저장하고 있어요.
    </p>
    <p v-if="saveError" class="form-error" role="alert">{{ saveError }}</p>
    <form class="search-field" @submit.prevent="search()">
      <AppIcon name="search" /><input
        ref="input"
        v-model="query"
        type="search"
        minlength="2"
        maxlength="100"
        placeholder="지역명 일부, 예: 서울 · 강남 · 서귀포"
        aria-label="지역명"
        autocomplete="off"
      /><button class="text-button" type="submit" :disabled="query.trim().length < 2">검색</button>
    </form>
    <p v-if="locations.length" class="search-result-count" role="status">
      {{ total.toLocaleString('ko-KR') }}개 지역 중 {{ locations.length.toLocaleString('ko-KR') }}개
      표시
    </p>
    <div class="region-results" aria-live="polite" :aria-busy="loading">
      <p v-if="loading && !locations.length" class="search-message">
        <span class="spinner" />동네를 찾고 있어요.
      </p>
      <div v-else-if="error && !locations.length" class="search-message">
        <p>{{ error }}</p>
        <button class="text-button" @click="search()">다시 검색</button>
      </div>
      <template v-else-if="locations.length"
        ><button
          v-for="location in locations"
          :key="location.id"
          :disabled="busy"
          class="region-result"
          @click="emit('select', location)"
        >
          <span class="location-symbol"><AppIcon name="pin" /></span
          ><span
            ><strong>{{ location.name }}</strong
            ><small>{{ locationLabel(location) }}</small></span
          ><AppIcon name="arrow" :size="18" /></button
      ></template>
      <p v-else-if="searched" class="search-message">
        검색 결과가 없어요. 지역명 일부나 시·군·구 이름으로 다시 찾아보세요.
      </p>
      <div v-else class="search-suggestions">
        <span class="muted">이렇게 검색해 보세요</span
        ><button
          v-for="city in ['서울', '부산', '제주']"
          :key="city"
          class="suggestion"
          @click="query = city"
        >
          {{ city }}<AppIcon name="arrow" :size="14" />
        </button>
      </div>
    </div>
    <template v-if="locations.length">
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <button
        v-if="hasMore"
        class="secondary-button full-width more-results"
        :disabled="loading"
        @click="search(true)"
      >
        <span v-if="loading" class="spinner" />{{
          loading
            ? '다음 지역을 불러오고 있어요'
            : error
              ? '더 보기 다시 시도'
              : '관련 지역 더 보기'
        }}
      </button>
    </template>
    <p v-if="attribution && locations.length" class="micro source-note">
      지역 데이터 · {{ attribution }}
      <a
        v-if="attribution.includes('GeoNames')"
        href="https://www.geonames.org/"
        target="_blank"
        rel="noopener noreferrer"
        >출처</a
      >
    </p>
    <p class="modal-footnote">
      <AppIcon name="info" :size="15" />선택한 지역으로 날씨와 옷차림을 확인해요.
    </p>
  </dialog>
</template>
