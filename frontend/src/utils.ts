import type { Location } from './types'

export const degrees = (value: number | null | undefined) =>
  value == null ? '—' : `${Math.round(value)}°`
export const metric = (value: number | null | undefined, unit: string) =>
  value == null ? '정보 없음' : `${value}${unit}`
export const dateLabel = (value: string, weekday = false) =>
  new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    month: 'long',
    day: 'numeric',
    ...(weekday ? { weekday: 'long' as const } : {}),
  }).format(new Date(`${value.slice(0, 10)}T12:00:00+09:00`))
export const kstDate = () =>
  new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date())
export const timeLabel = (value: string | null | undefined) =>
  value
    ? new Intl.DateTimeFormat('ko-KR', {
        timeZone: 'Asia/Seoul',
        month: 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(new Date(value))
    : '시각 정보 없음'
export const locationLabel = (location: Location) =>
  [...new Set([location.admin1, location.admin2, location.name].filter(Boolean))].join(' ')
export const hourLabel = (time: string) =>
  new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: 'numeric',
    hour12: false,
  }).format(new Date(time))

export const preferenceOptions = [
  {
    key: 'cold_sensitivity',
    label: '체감 온도',
    description: '같은 날씨도 다르게 느끼니까',
    options: [
      ['normal', '보통이에요'],
      ['cold', '추위를 타요'],
      ['warm', '더위를 타요'],
    ],
  },
  {
    key: 'style',
    label: '선호하는 스타일',
    description: '오늘 나에게 어울리는 분위기',
    options: [
      ['default', '상관없어요'],
      ['casual', '편안하게'],
      ['formal', '단정하게'],
    ],
  },
  {
    key: 'activity',
    label: '오늘의 활동',
    description: '어디에서 하루를 보내나요?',
    options: [
      ['daily', '일상생활'],
      ['outdoor', '야외활동'],
      ['active', '활동량 많음'],
    ],
  },
] as const

export const clothingOptions = [
  ['any', '모두 괜찮아요'],
  ['menswear', '남성복 위주'],
  ['womenswear', '여성복 위주'],
] as const
export const avoidOptions = [
  ['skirts', '치마'],
  ['dresses', '원피스'],
  ['shorts', '반바지'],
  ['sandals', '샌들'],
  ['heels', '굽 높은 신발'],
  ['sleeveless', '민소매'],
] as const
export const defaultPreferences = () =>
  ({
    cold_sensitivity: 'normal',
    style: 'default',
    activity: 'daily',
    clothing_preference: 'any',
    avoid_items: [],
  }) as import('./types').Preferences

export function safeSource(value?: string) {
  try {
    const url = new URL(value || 'https://open-meteo.com/')
    return ['https:', 'http:'].includes(url.protocol) ? url.href : 'https://open-meteo.com/'
  } catch {
    return 'https://open-meteo.com/'
  }
}
