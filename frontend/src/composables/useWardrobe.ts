import { computed, onBeforeUnmount, ref } from 'vue'
import { ApiError, errorMessage, getOutfit, getWeather } from '../api'
import type { Account, Location, OutfitResult, Period, Preferences, WeatherResult } from '../types'
import { defaultPreferences, avoidOptions } from '../utils'

const defaults = defaultPreferences()
const storageKey = 'ondo.settings.v1'

function restore(): { location: Location | null; preferences: Preferences } {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || 'null')
    const candidate = value?.location
    const location =
      candidate &&
      Number.isSafeInteger(candidate.id) &&
      candidate.id > 0 &&
      typeof candidate.name === 'string' &&
      typeof candidate.latitude === 'number' &&
      Number.isFinite(candidate.latitude) &&
      Math.abs(candidate.latitude) <= 90 &&
      typeof candidate.longitude === 'number' &&
      Number.isFinite(candidate.longitude) &&
      Math.abs(candidate.longitude) <= 180 &&
      candidate.country_code === 'KR'
        ? (candidate as Location)
        : null
    const p = value?.preferences
    return {
      location,
      preferences: {
        cold_sensitivity: ['normal', 'cold', 'warm'].includes(p?.cold_sensitivity)
          ? p.cold_sensitivity
          : defaults.cold_sensitivity,
        style: ['default', 'casual', 'formal'].includes(p?.style) ? p.style : defaults.style,
        activity: ['daily', 'outdoor', 'active'].includes(p?.activity)
          ? p.activity
          : defaults.activity,
        clothing_preference: ['any', 'menswear', 'womenswear'].includes(p?.clothing_preference)
          ? p.clothing_preference
          : 'any',
        avoid_items: Array.isArray(p?.avoid_items)
          ? ([
              ...new Set(
                p.avoid_items.filter((item: unknown) =>
                  avoidOptions.some(([value]) => value === item),
                ),
              ),
            ].sort() as Preferences['avoid_items'])
          : [],
      },
    }
  } catch {
    return { location: null, preferences: { ...defaults } }
  }
}

export function useWardrobe() {
  const saved = restore()
  const location = ref<Location | null>(saved.location)
  const preferences = ref<Preferences>(saved.preferences)
  const period = ref<Period>('today')
  const weather = ref<WeatherResult | null>(null)
  const outfit = ref<OutfitResult | null>(null)
  const weatherLoading = ref(false)
  const outfitLoading = ref(false)
  const weatherError = ref('')
  const outfitError = ref('')
  const outfitErrorCode = ref('')
  const storageNotice = ref('')
  let weatherRequest: AbortController | null = null
  let outfitRequest: AbortController | null = null
  let signedIn = false

  function save() {
    if (signedIn) return
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({ location: location.value, preferences: preferences.value }),
      )
      storageNotice.value = ''
    } catch {
      storageNotice.value =
        '이 브라우저에서는 설정을 저장할 수 없어요. 현재 화면에서는 그대로 사용할 수 있어요.'
    }
  }

  async function loadWeather() {
    weatherRequest?.abort()
    const selected = location.value
    if (!selected) return
    const controller = new AbortController()
    weatherRequest = controller
    weatherLoading.value = true
    weatherError.value = ''
    try {
      const result = await getWeather(selected, period.value, controller.signal)
      if (weatherRequest === controller) weather.value = result
    } catch (error) {
      if (!controller.signal.aborted) weatherError.value = errorMessage(error)
    } finally {
      if (weatherRequest === controller) weatherLoading.value = false
    }
  }

  async function loadOutfit() {
    outfitRequest?.abort()
    const selected = location.value
    if (!selected) return
    const controller = new AbortController()
    outfitRequest = controller
    outfitLoading.value = true
    outfitError.value = ''
    outfitErrorCode.value = ''
    try {
      const result = await getOutfit(selected, period.value, preferences.value, controller.signal)
      if (outfitRequest === controller) outfit.value = result
    } catch (error) {
      if (!controller.signal.aborted) {
        outfitError.value = errorMessage(error)
        outfitErrorCode.value = error instanceof ApiError ? error.code : ''
      }
    } finally {
      if (outfitRequest === controller) outfitLoading.value = false
    }
  }

  function reload() {
    weatherRequest?.abort()
    outfitRequest?.abort()
    weatherRequest = null
    outfitRequest = null
    weather.value = null
    outfit.value = null
    weatherError.value = ''
    outfitError.value = ''
    weatherLoading.value = false
    outfitLoading.value = false
    void loadWeather()
    void loadOutfit()
  }
  function selectLocation(value: Location) {
    location.value = value
    save()
    reload()
  }
  function selectPeriod(value: Period) {
    if (period.value !== value) {
      period.value = value
      reload()
    }
  }
  function applyPreferences(value: Preferences) {
    if (JSON.stringify(value) === JSON.stringify(preferences.value)) return
    preferences.value = { ...value }
    save()
    outfit.value = null
    void loadOutfit()
  }
  const isPersonalized = computed(
    () =>
      preferences.value.cold_sensitivity !== 'normal' ||
      preferences.value.style !== 'default' ||
      preferences.value.activity !== 'daily' ||
      preferences.value.clothing_preference !== 'any' ||
      preferences.value.avoid_items.length > 0,
  )
  onBeforeUnmount(() => {
    weatherRequest?.abort()
    outfitRequest?.abort()
  })
  function adoptAccount(account: Account | null) {
    signedIn = !!account
    const next = account
      ? { location: account.profile.location, preferences: account.profile.preferences }
      : restore()
    location.value = next.location
    preferences.value = {
      ...defaultPreferences(),
      ...next.preferences,
      avoid_items: [...(next.preferences.avoid_items || [])],
    }
    storageNotice.value = ''
    reload()
  }
  return {
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
  }
}
