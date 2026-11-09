<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import AuthPage from './components/AuthPage.vue'
import ProfilePage from './components/ProfilePage.vue'
import { useAccount } from './composables/useAccount'
import AppIcon from './components/AppIcon.vue'
import WeatherIcon from './components/WeatherIcon.vue'
import WardrobeArt from './components/WardrobeArt.vue'
import RegionPicker from './components/RegionPicker.vue'
import PreferenceDialog from './components/PreferenceDialog.vue'
import OutfitCard from './components/OutfitCard.vue'
import FeedbackDialog from './components/FeedbackDialog.vue'
import FeedbackReviewPage from './components/FeedbackReviewPage.vue'
import { useWardrobe } from './composables/useWardrobe'
import {
  dateLabel,
  degrees,
  hourLabel,
  kstDate,
  locationLabel,
  metric,
  preferenceOptions,
  safeSource,
  timeLabel,
} from './utils'
import type { GeneratedDay, Location, Preferences, ProfileInput, WeatherDay } from './types'

const {
  location,
  preferences,
  period,
  weather,
  outfit,
  weatherLoading,
  outfitLoading,
  weatherError,
  outfitError,
  outfitErrorCode,
  storageNotice,
  isPersonalized,
  selectLocation,
  selectPeriod,
  applyPreferences,
  loadWeather,
  loadOutfit,
  adoptAccount,
} = useWardrobe()
const {
  account,
  ready: accountReady,
  busy: accountBusy,
  error: accountError,
  signIn,
  saveProfile,
  signOut,
} = useAccount()
const feedbackTarget = ref<{ generationId: string; day: GeneratedDay } | null>(null)
const feedbackTrigger = ref<HTMLButtonElement>()
const feedbackSession = ref(0)
watch(
  () => account.value?.user.id,
  () => {
    feedbackSession.value++
    feedbackTarget.value = null
  },
  { flush: 'sync' },
)
type View = 'home' | 'login' | 'register' | 'profile' | 'review'
function hashView(): View {
  return (
    (
      {
        '#login': 'login',
        '#signup': 'register',
        '#profile': 'profile',
        '#review': 'review',
      } as Record<string, View>
    )[window.location.hash] || 'home'
  )
}
const view = ref<View>(hashView())
const notification = ref('')
function navigate(value: View) {
  accountError.value = ''
  view.value = value
  window.location.hash = {
    home: 'main-content',
    login: 'login',
    register: 'signup',
    profile: 'profile',
    review: 'review',
  }[value]
  window.scrollTo({ top: 0 })
}
const onHashChange = () => {
  view.value = hashView()
  if (accountReady.value && !account.value && view.value === 'review') navigate('login')
}
window.addEventListener('hashchange', onHashChange)
onBeforeUnmount(() => window.removeEventListener('hashchange', onHashChange))
watch(
  [accountReady, account],
  ([ready]) => {
    if (!ready) return
    adoptAccount(account.value)
    if ((view.value === 'profile' || view.value === 'review') && !account.value) navigate('login')
  },
  { immediate: true },
)
async function submitAuth(values: { email: string; password: string; name?: string }) {
  const mode = view.value === 'register' ? 'register' : 'login'
  if (await signIn(mode, values)) navigate(account.value?.profile.location ? 'home' : 'profile')
}
async function submitProfile(values: ProfileInput) {
  if (await saveProfile(values)) {
    notification.value = '나의 추천 프로필을 저장했어요.'
    navigate('home')
  }
}
async function logout() {
  feedbackTarget.value = null
  feedbackSession.value++
  if (view.value === 'review') navigate('home')
  if (await signOut()) {
    notification.value = '로그아웃했어요. 이 브라우저의 둘러보기 설정으로 돌아왔어요.'
    navigate('home')
  }
}
const regionOpen = ref(false)
const preferencesOpen = ref(false)
const regionTrigger = ref<HTMLButtonElement>()
const preferenceTrigger = ref<HTMLButtonElement>()
const selectedDay = ref(kstDate())
const avoidOpen = ref(false)
// 최신 날씨 조회만 실패한 경우에도 저장된 추천의 날짜는 계속 선택할 수 있다.
const weeklyDays = computed<WeatherDay[]>(
  () =>
    weather.value?.daily ??
    outfit.value?.daily?.map((day) => ({
      ...day.weather,
      date: day.date,
      precipitation_probability_max_percent: day.weather.precipitation_probability_percent,
      precipitation_sum_mm: day.weather.precipitation_mm,
      wind_speed_max_m_s: day.weather.wind_speed_m_s,
    })) ??
    [],
)
watch(weeklyDays, (days) => {
  if (days.length && !days.some((day) => day.date === selectedDay.value))
    selectedDay.value = days[0]!.date
})
watch(period, () => {
  avoidOpen.value = false
  selectedDay.value = kstDate()
})
watch(location, () => {
  avoidOpen.value = false
})
const recommendation = computed(() =>
  period.value === 'today'
    ? outfit.value?.recommendation
    : outfit.value?.daily?.find((day) => day.date === selectedDay.value),
)
const feedbackGenerationId = computed(() => {
  const result = outfit.value
  const engine = result?.personalization.llm_used ? result.personalization.engine : result?.engine
  const id = engine?.generation_id
  return id && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)
    ? id
    : null
})
function openFeedback() {
  if (!account.value) {
    navigate('login')
    return
  }
  const day = recommendation.value
  const generationId = feedbackGenerationId.value
  if (!day || !generationId) return
  feedbackTarget.value = {
    generationId,
    day: JSON.parse(
      JSON.stringify({
        date: day.date,
        best: day.best,
        worst: day.worst,
        reasons: day.reasons,
        avoid_reasons: day.avoid_reasons,
        precautions: day.precautions,
      }),
    ),
  }
}
async function closeFeedback(saved = false) {
  feedbackTarget.value = null
  if (saved) notification.value = '신고를 저장했어요. 내 수정안 검수에서 확인해 주세요.'
  await nextTick()
  feedbackTrigger.value?.focus()
}
function feedbackExpired() {
  feedbackTarget.value = null
  feedbackSession.value++
  account.value = null
  navigate('login')
  accountError.value = '세션이 만료되었어요. 다시 로그인해 주세요.'
}
const dayWeather = computed(() =>
  period.value === 'today'
    ? weather.value?.today
    : weeklyDays.value.find((day) => day.date === selectedDay.value),
)
const currentWeather = computed(() =>
  period.value === 'today' ? weather.value?.current : undefined,
)
const hours = computed(() =>
  (weather.value?.hourly || []).filter((hour) =>
    [6, 9, 12, 15, 18, 21].includes(Number(hour.time.slice(11, 13))),
  ),
)
const preferenceTags = computed(() =>
  preferenceOptions.map(
    (group) => group.options.find(([value]) => value === preferences.value[group.key])?.[1],
  ),
)
const wardrobeNames: Record<string, string> = {
  tops: '상의',
  bottoms: '하의',
  one_pieces: '원피스',
  outerwear: '겉옷',
  shoes: '신발',
  accessories: '준비물',
}
const wardrobeGroups = computed(() =>
  Object.entries(outfit.value?.wardrobe || {}).filter(([, items]) => items.length),
)
const isWeeklyWaiting = computed(() => outfitErrorCode.value === 'OUTFIT_WEEKLY_NOT_READY')
const forecastIsOlder = computed(
  () => !!outfit.value?.forecast_start_date && outfit.value.forecast_start_date !== kstDate(),
)

async function closeRegion() {
  regionOpen.value = false
  await nextTick()
  regionTrigger.value?.focus()
}
async function chooseLocation(value: Location) {
  if (account.value) {
    if (
      !(await saveProfile({
        name: account.value.user.name,
        location_id: value.id,
        preferences: preferences.value,
      }))
    )
      return
  } else selectLocation(value)
  await closeRegion()
}
async function closePreferences() {
  preferencesOpen.value = false
  await nextTick()
  preferenceTrigger.value?.focus()
}
async function choosePreferences(value: Preferences) {
  if (account.value) {
    if (
      !(await saveProfile({
        name: account.value.user.name,
        location_id: location.value?.id || null,
        preferences: value,
      }))
    )
      return
  } else applyPreferences(value)
  await closePreferences()
}

function chooseDay(date: string) {
  selectedDay.value = date
  avoidOpen.value = false
}
</script>

<template>
  <FeedbackReviewPage
    v-if="view === 'review' && accountReady && account"
    :key="`${account.user.id}:${feedbackSession}`"
    @close="navigate('home')"
    @logout="logout"
    @expired="feedbackExpired"
  />
  <p v-else-if="view === 'review' && !accountReady" role="status">로그인 확인 중</p>
  <AuthPage
    v-else-if="view === 'login' || view === 'register'"
    :mode="view"
    :busy="accountBusy || !accountReady"
    :error="accountError"
    @submit="submitAuth"
    @navigate="navigate"
  />
  <ProfilePage
    v-else-if="view === 'profile' && account"
    :key="account.user.id"
    :account="account"
    :busy="accountBusy"
    :error="accountError"
    @save="submitProfile"
    @close="navigate('home')"
  />
  <template v-else>
    <a class="skip-link" href="#main-content">본문으로 이동</a>
    <div class="app-shell">
      <aside class="sidebar" aria-label="주 메뉴">
        <a href="#main-content" class="brand" aria-label="온도 홈"
          ><span class="brand-symbol">o<span>°</span></span
          ><span>온도<small>날씨를 입는 일상</small></span></a
        >
        <div class="sidebar-section-label">MY DAILY GUIDE</div>
        <nav class="main-nav">
          <button
            :class="{ active: period === 'today' }"
            :aria-current="period === 'today' ? 'page' : undefined"
            @click="selectPeriod('today')"
          >
            <AppIcon name="sun" /><span>오늘의 옷차림</span><span class="nav-dot" /></button
          ><button
            :class="{ active: period === 'weekly' }"
            :aria-current="period === 'weekly' ? 'page' : undefined"
            @click="selectPeriod('weekly')"
          >
            <AppIcon name="calendar" /><span>일주일 미리보기</span><span class="nav-dot" />
          </button>
        </nav>
        <div class="sidebar-note">
          <span class="tiny-leaf"><AppIcon name="leaf" :size="25" /></span>
          <p>날씨에 맞게,<br />나답게 입는 하루.</p>
          <small>매일의 작은 고민을<br />온도와 함께 덜어보세요.</small>
        </div>
        <div class="sidebar-bottom">
          <span class="status-dot" />WEATHER MEETS WARDROBE<span class="sidebar-version"
            >온도 · MVP</span
          >
        </div>
      </aside>

      <div class="workspace">
        <header class="topbar">
          <span class="topbar-caption">A GOOD DAY STARTS WITH A GOOD FIT.</span
          ><a class="mobile-brand" href="#main-content">온도<span>°</span></a>
          <div class="topbar-actions">
            <button v-if="account" class="account-button" @click="navigate('review')">
              내 수정안 검수
            </button>
            <button ref="regionTrigger" class="location-button" @click="regionOpen = true">
              <AppIcon name="pin" :size="17" /><span>{{
                location ? location.name : '내 지역 선택'
              }}</span
              ><AppIcon name="chevron" :size="14" /></button
            ><button v-if="account" class="account-button" @click="navigate('profile')">
              <AppIcon name="sliders" :size="16" /><span>{{ account.user.name }} 님</span></button
            ><button
              v-else
              class="account-button"
              :disabled="!accountReady"
              @click="navigate('login')"
            >
              {{ accountReady ? '로그인 · 회원가입' : '로그인 확인 중'
              }}<AppIcon name="arrow" :size="15" /></button
            ><button
              v-if="account"
              class="icon-button"
              :disabled="accountBusy"
              aria-label="로그아웃"
              @click="logout"
            >
              <AppIcon name="logout" :size="18" />
            </button>
          </div>
        </header>

        <main id="main-content" tabindex="-1">
          <p v-if="notification" class="success-notice" role="status">
            {{ notification
            }}<button class="icon-button" aria-label="알림 닫기" @click="notification = ''">
              <AppIcon name="close" :size="15" />
            </button>
          </p>
          <p v-if="accountError && !regionOpen && !preferencesOpen" class="form-error" role="alert">
            {{ accountError }}
          </p>
          <div class="page-heading">
            <div>
              <p class="eyebrow">
                {{ period === 'today' ? 'YOUR DAILY WEATHER WARDROBE' : 'A LITTLE LOOK AHEAD' }}
              </p>
              <h1>
                {{ period === 'today' ? '오늘, 뭐 입지' : '일주일을 가볍게 준비해요'
                }}<span class="heading-dot">{{ period === 'today' ? '?' : '.' }}</span>
              </h1>
              <p class="page-subtitle">
                {{
                  period === 'today'
                    ? '오늘의 날씨에, 나의 취향을 더해요.'
                    : '날씨부터 옷차림까지, 미리 알아두면 편하니까.'
                }}
              </p>
            </div>
            <span class="heading-date"
              >{{ dateLabel(kstDate(), true) }}<span>SEOUL TIME · KST</span></span
            >
          </div>

          <div class="view-toolbar">
            <div class="view-tabs" aria-label="추천 기간">
              <button
                :class="{ selected: period === 'today' }"
                :aria-pressed="period === 'today'"
                @click="selectPeriod('today')"
              >
                오늘<AppIcon name="sun" :size="15" /></button
              ><button
                :class="{ selected: period === 'weekly' }"
                :aria-pressed="period === 'weekly'"
                @click="selectPeriod('weekly')"
              >
                일주일<AppIcon name="calendar" :size="15" />
              </button>
            </div>
            <span class="toolbar-caption">{{
              location ? locationLabel(location) : '우리 동네에서 시작하는 하루'
            }}</span>
          </div>

          <template v-if="!location">
            <section class="welcome-card">
              <div class="welcome-copy">
                <span class="pill"><span class="status-dot" />당신을 위한 데일리 가이드</span>
                <h2>날씨를 알면,<br />옷 고르기가<br /><em>조금 더 쉬워져요.</em></h2>
                <p>
                  우리 동네 날씨와 나의 취향을 바탕으로<br />오늘 입기 좋은 옷차림을 만나보세요.
                </p>
                <button class="primary-button" @click="regionOpen = true">
                  우리 동네 찾아보기<AppIcon name="arrow" :size="18" />
                </button>
              </div>
              <div class="welcome-illustration">
                <span class="illustration-label">THE ART OF GETTING DRESSED</span
                ><WardrobeArt /><span class="illustration-caption"
                  >날씨와 취향 사이, 나에게 맞는 한 벌.</span
                >
              </div>
            </section>
            <div class="intro-grid">
              <article>
                <span class="intro-icon"><AppIcon name="sun" :size="24" /></span
                ><span class="intro-number">01</span>
                <h3>외출 전, 날씨 한눈에</h3>
                <p>현재 기온부터 시간별 예보까지.<br />하루의 온도 변화를 살펴보세요.</p>
              </article>
              <article>
                <span class="intro-icon"><AppIcon name="hanger" :size="24" /></span
                ><span class="intro-number">02</span>
                <h3>날씨에 어울리는 옷차림</h3>
                <p>무엇을 입고, 무엇을 피할지.<br />추천 이유까지 함께 알려드려요.</p>
              </article>
              <article>
                <span class="intro-icon"><AppIcon name="sliders" :size="24" /></span
                ><span class="intro-number">03</span>
                <h3>조금 더 나답게</h3>
                <p>추위 민감도, 스타일, 활동 계획.<br />나의 취향을 추천에 더해 보세요.</p>
              </article>
            </div>
          </template>

          <template v-else>
            <p v-if="storageNotice" class="inline-notice" role="status">{{ storageNotice }}</p>
            <section
              v-if="period === 'weekly'"
              class="weekly-strip"
              aria-label="7일 날씨"
              :aria-busy="weatherLoading"
            >
              <template v-if="weeklyDays.length"
                ><button
                  v-for="day in weeklyDays"
                  :key="day.date"
                  class="day-button"
                  :class="{ selected: selectedDay === day.date }"
                  :aria-pressed="selectedDay === day.date"
                  @click="chooseDay(day.date)"
                >
                  <span>{{
                    day.date === kstDate()
                      ? '오늘'
                      : new Intl.DateTimeFormat('ko-KR', {
                          weekday: 'short',
                          timeZone: 'Asia/Seoul',
                        }).format(new Date(`${day.date}T12:00:00+09:00`))
                  }}</span
                  ><small>{{ day.date.slice(5).replace('-', '.') }}</small
                  ><WeatherIcon :code="day.weather_code" :size="38" /><strong
                    >{{ degrees(day.temperature_max_c) }}
                    <span>{{ degrees(day.temperature_min_c) }}</span></strong
                  ><small>{{ metric(day.precipitation_probability_max_percent, '%') }}</small>
                </button></template
              >
              <p v-else-if="weatherLoading" class="loading-line">
                <span class="spinner" />일주일 날씨를 불러오고 있어요.
              </p>
            </section>

            <div class="dashboard-grid">
              <section
                class="weather-panel panel"
                aria-labelledby="weather-title"
                :aria-busy="weatherLoading"
              >
                <div class="section-heading">
                  <span class="eyebrow" id="weather-title">{{
                    period === 'today' ? 'TODAY’S WEATHER' : 'DAILY WEATHER'
                  }}</span
                  ><button
                    class="icon-button"
                    aria-label="날씨 다시 불러오기"
                    :disabled="weatherLoading"
                    @click="loadWeather"
                  >
                    <AppIcon name="refresh" :size="16" />
                  </button>
                </div>
                <template v-if="weatherLoading"
                  ><div class="weather-skeleton">
                    <div class="skeleton sk-short" />
                    <div class="skeleton sk-temp" />
                    <div class="skeleton" />
                    <span class="muted">날씨를 불러오고 있어요.</span>
                  </div></template
                >
                <div v-else-if="weatherError" class="state-message" role="alert">
                  <AppIcon name="info" :size="28" />
                  <h3>날씨를 불러오지 못했어요</h3>
                  <p>{{ weatherError }}</p>
                  <button class="secondary-button" @click="loadWeather">다시 시도</button>
                </div>
                <template v-else-if="dayWeather">
                  <div class="weather-location">
                    <AppIcon name="pin" :size="15" />{{ location.name
                    }}<span>{{ dateLabel(dayWeather.date) }}</span>
                  </div>
                  <div class="temperature-display">
                    <div>
                      <span class="current-temperature">{{
                        degrees(currentWeather?.temperature_c ?? dayWeather.temperature_max_c)
                      }}</span>
                      <p>
                        {{ currentWeather?.description || dayWeather.description
                        }}<span v-if="!currentWeather"> · 최고기온</span>
                      </p>
                    </div>
                    <WeatherIcon
                      :code="currentWeather?.weather_code ?? dayWeather.weather_code"
                      :night="currentWeather ? !currentWeather.is_day : false"
                      :size="98"
                    />
                  </div>
                  <div class="temperature-range">
                    <span
                      >최저 <strong>{{ degrees(dayWeather.temperature_min_c) }}</strong></span
                    ><span class="range-divider" /><span
                      >최고 <strong>{{ degrees(dayWeather.temperature_max_c) }}</strong></span
                    ><span v-if="currentWeather" class="feels-like"
                      >체감 {{ degrees(currentWeather.apparent_temperature_c) }}</span
                    >
                  </div>
                  <p v-if="period === 'today' && weather?.summary" class="weather-summary">
                    {{ weather.summary }}
                  </p>
                  <div class="weather-metrics">
                    <div>
                      <AppIcon name="drop" :size="19" /><span>최대 강수확률</span
                      ><strong>{{
                        metric(dayWeather.precipitation_probability_max_percent, '%')
                      }}</strong>
                    </div>
                    <div>
                      <AppIcon name="wind" :size="19" /><span>{{
                        currentWeather ? '현재 바람' : '최대 풍속'
                      }}</span
                      ><strong>{{
                        metric(
                          currentWeather
                            ? currentWeather.wind_speed_m_s
                            : dayWeather.wind_speed_max_m_s,
                          'm/s',
                        )
                      }}</strong>
                    </div>
                    <div>
                      <AppIcon :name="currentWeather ? 'thermometer' : 'drop'" :size="19" /><span>{{
                        currentWeather ? '현재 습도' : '누적 강수량'
                      }}</span
                      ><strong>{{
                        currentWeather
                          ? metric(currentWeather.humidity_percent, '%')
                          : metric(dayWeather.precipitation_sum_mm, 'mm')
                      }}</strong>
                    </div>
                  </div>
                  <div v-if="hours.length && period === 'today'" class="hourly-section">
                    <div class="mini-heading">
                      <h3>시간별 날씨</h3>
                      <span>오늘 · KST</span>
                    </div>
                    <div class="hourly-list">
                      <div v-for="hour in hours" :key="hour.time">
                        <span>{{ hourLabel(hour.time) }}</span
                        ><WeatherIcon
                          :code="hour.weather_code"
                          :night="Number(hour.time.slice(11, 13)) >= 18"
                          :size="31"
                        /><strong>{{ degrees(hour.temperature_c) }}</strong
                        ><small>{{ metric(hour.precipitation_probability_percent, '%') }}</small>
                      </div>
                    </div>
                  </div>
                  <p class="weather-timestamp">
                    {{ timeLabel(currentWeather?.time || weather?.fetched_at) }}
                    {{ currentWeather ? '기상 모델 기준' : '조회' }}
                  </p>
                </template>
                <a
                  class="weather-source"
                  :href="safeSource(weather?.source_url)"
                  target="_blank"
                  rel="noopener noreferrer"
                  >Weather data by {{ weather?.provider || 'Open-Meteo'
                  }}<AppIcon name="arrow" :size="13"
                /></a>
              </section>

              <section
                class="recommendation-panel"
                aria-labelledby="outfit-title"
                :aria-busy="outfitLoading"
              >
                <div class="recommendation-heading">
                  <div>
                    <p class="eyebrow">DRESS FOR THE DAY</p>
                    <h2 id="outfit-title">
                      {{
                        period === 'today'
                          ? '오늘을 위한 옷차림'
                          : `${dateLabel(selectedDay)}의 옷차림`
                      }}
                    </h2>
                  </div>
                  <span class="small-label"
                    ><AppIcon :name="isPersonalized ? 'sparkles' : 'hanger'" :size="14" />{{
                      isPersonalized ? '취향을 더한 추천' : '우리 동네 추천'
                    }}</span
                  >
                </div>
                <div v-if="outfitLoading" class="outfit-loading panel" role="status">
                  <div class="loading-hanger"><AppIcon name="hanger" :size="46" /></div>
                  <h3>오늘의 한 벌을 고르고 있어요.</h3>
                  <p>
                    날씨와 선택한 취향을 살펴보고 있어요.<br />처음 준비하는 추천은 몇 분 걸릴 수
                    있어요.
                  </p>
                  <span class="loading-line"
                    ><span class="spinner" />{{
                      period === 'weekly'
                        ? '준비된 주간 추천 확인 중'
                        : '나에게 맞는 옷차림 준비 중'
                    }}</span
                  >
                </div>
                <div
                  v-else-if="outfitError"
                  class="outfit-empty panel"
                  :role="isWeeklyWaiting ? 'status' : 'alert'"
                >
                  <span class="empty-icon"
                    ><AppIcon :name="isWeeklyWaiting ? 'calendar' : 'hanger'" :size="36"
                  /></span>
                  <h3>
                    {{
                      isWeeklyWaiting
                        ? '일주일의 옷장을 준비하고 있어요.'
                        : '추천을 잠시 불러오지 못했어요.'
                    }}
                  </h3>
                  <p>{{ outfitError }}</p>
                  <button class="secondary-button" @click="loadOutfit">
                    <AppIcon name="refresh" :size="16" />{{
                      isWeeklyWaiting ? '준비 상태 다시 확인' : '추천 다시 불러오기'
                    }}
                  </button>
                </div>
                <template v-else-if="recommendation">
                  <p v-if="outfit?.region" class="recommendation-region">
                    <AppIcon name="pin" :size="13" />{{ outfit.region.name }} 대표 위치의 예보로
                    준비했어요.
                  </p>
                  <p v-if="forecastIsOlder" class="inline-notice">
                    <AppIcon name="clock" :size="16" />{{ dateLabel(outfit!.forecast_start_date!) }}
                    예보 기준 추천이에요. 왼쪽 날씨는 최신 조회 결과예요.
                  </p>
                  <OutfitCard :look="recommendation.best" :reasons="recommendation.reasons" />
                  <div class="feedback-entry">
                    <button
                      ref="feedbackTrigger"
                      class="secondary-button"
                      :disabled="!feedbackGenerationId || !accountReady"
                      @click="openFeedback"
                    >
                      답변 문제 신고·수정
                    </button>
                    <p v-if="!feedbackGenerationId" role="status">
                      이 답변에는 생성 기록 ID가 없어 신고·수정을 사용할 수 없어요.
                    </p>
                    <p v-else-if="!account">
                      로그인 후 이 답변의 문제를 신고하거나 수정할 수 있어요.
                    </p>
                  </div>
                  <div v-if="recommendation.precautions.length" class="precaution-note">
                    <AppIcon name="leaf" :size="20" />
                    <div>
                      <strong>외출 전, 이것도 챙겨요</strong>
                      <p v-for="note in recommendation.precautions" :key="note">{{ note }}</p>
                    </div>
                  </div>
                  <button
                    class="avoid-toggle"
                    :aria-expanded="avoidOpen"
                    aria-controls="avoid-look"
                    @click="avoidOpen = !avoidOpen"
                  >
                    <span><AppIcon name="info" :size="17" />이런 옷차림은 피하는 게 좋아요</span
                    ><AppIcon :name="avoidOpen ? 'close' : 'chevron'" :size="16" />
                  </button>
                  <OutfitCard
                    v-if="avoidOpen"
                    id="avoid-look"
                    :look="recommendation.worst"
                    :reasons="recommendation.avoid_reasons"
                    avoid
                  />
                  <div
                    v-if="outfit?.personalization.adjustments.length"
                    class="personalization-notes"
                  >
                    <p v-for="note in outfit.personalization.adjustments" :key="note">{{ note }}</p>
                  </div>
                  <p class="recommendation-timestamp">
                    {{ timeLabel(outfit?.personalization.generated_at || outfit?.generated_at) }}
                    준비 · 날씨 조회 {{ timeLabel(outfit?.fetched_at) }}
                  </p>
                </template>
                <div v-else-if="outfit" class="outfit-empty panel">
                  <AppIcon name="calendar" :size="32" />
                  <h3>선택한 날짜의 추천이 없어요.</h3>
                  <p>
                    저장된 추천은 {{ dateLabel(outfit.forecast_start_date || selectedDay) }}부터의
                    예보를 기준으로 해요. 다른 날짜를 선택해 주세요.
                  </p>
                </div>
              </section>
            </div>

            <section class="personalize-banner">
              <span class="personalize-icon"><AppIcon name="sliders" :size="25" /></span>
              <div>
                <h3>같은 날씨, 나에게 맞는 옷차림.</h3>
                <p>
                  {{ preferenceTags.join(' · ')
                  }}<span v-if="!isPersonalized"> — 취향을 더하면 추천도 달라져요.</span>
                </p>
              </div>
              <button
                ref="preferenceTrigger"
                class="secondary-button"
                @click="preferencesOpen = true"
              >
                내 취향 설정<AppIcon name="arrow" :size="16" />
              </button>
              <button v-if="account" class="text-button profile-link" @click="navigate('profile')">
                전체 프로필
              </button>
            </section>

            <section v-if="period === 'weekly' && outfit?.wardrobe" class="wardrobe-panel panel">
              <div class="section-heading">
                <div>
                  <p class="eyebrow">YOUR WEEKLY CHECKLIST</p>
                  <h2>이번 주, 옷장에 준비해요.</h2>
                </div>
                <AppIcon name="hanger" :size="28" />
              </div>
              <p v-if="outfit.summary" class="muted">{{ outfit.summary }}</p>
              <div class="wardrobe-groups">
                <div v-for="[key, items] in wardrobeGroups" :key="key">
                  <h3>{{ wardrobeNames[key] }}</h3>
                  <span v-for="item in items" :key="item" class="wardrobe-item">{{ item }}</span>
                </div>
              </div>
            </section>
            <p class="recommendation-notice">
              <AppIcon name="info" :size="14" />{{
                outfit?.notice ||
                '날씨 기반의 참고 추천이에요. 실제 날씨와 나의 체감에 맞춰 조절해 주세요.'
              }}
            </p>
          </template>

          <footer class="page-footer">
            <span class="footer-brand">온도<span>°</span></span>
            <p>오늘의 온도에, 나다운 하루를.</p>
            <span>WEAR THE WEATHER, YOUR WAY.</span>
          </footer>
        </main>
      </div>
    </div>
    <RegionPicker
      v-if="regionOpen"
      :busy="accountBusy"
      :save-error="accountError"
      @close="closeRegion"
      @select="chooseLocation"
    />
    <FeedbackDialog
      v-if="feedbackTarget && account"
      :key="`${account.user.id}:${feedbackSession}`"
      :generation-id="feedbackTarget.generationId"
      :day="feedbackTarget.day"
      @close="closeFeedback()"
      @saved="closeFeedback(true)"
      @expired="feedbackExpired"
    />
    <PreferenceDialog
      v-if="preferencesOpen"
      :value="preferences"
      :busy="accountBusy"
      :error="accountError"
      @close="closePreferences"
      @apply="choosePreferences"
    />
  </template>
</template>

<style src="./feedback.css"></style>
