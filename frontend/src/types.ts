export type Period = 'today' | 'weekly'
export interface Location {
  id: number
  name: string
  latitude: number
  longitude: number
  country_code: string
  country: string | null
  admin1: string | null
  admin2: string | null
  timezone: string | null
}
export interface Preferences {
  cold_sensitivity: 'normal' | 'cold' | 'warm'
  style: 'default' | 'casual' | 'formal'
  activity: 'daily' | 'outdoor' | 'active'
  clothing_preference: 'any' | 'menswear' | 'womenswear'
  avoid_items: ('skirts' | 'dresses' | 'shorts' | 'sandals' | 'heels' | 'sleeveless')[]
}
export interface Account {
  user: { id: string; name: string; email: string }
  profile: { location: Location | null; preferences: Preferences }
}
export interface ProfileInput {
  name: string
  location_id: number | null
  preferences: Preferences
}
export interface WeatherDay {
  date: string
  temperature_min_c: number
  temperature_max_c: number
  apparent_temperature_min_c: number | null
  apparent_temperature_max_c: number | null
  precipitation_probability_max_percent: number | null
  precipitation_sum_mm: number | null
  wind_speed_max_m_s: number | null
  weather_code: number
  description: string
}
export interface CurrentWeather {
  time: string
  temperature_c: number
  apparent_temperature_c: number | null
  humidity_percent: number | null
  wind_speed_m_s: number | null
  description: string
  weather_code: number
  is_day: boolean
}
export interface HourlyWeather {
  time: string
  temperature_c: number
  weather_code: number
  description: string
  precipitation_probability_percent: number | null
}
export interface WeatherResult {
  fetched_at: string
  source_url: string
  provider: string
  current?: CurrentWeather
  today?: WeatherDay
  hourly?: HourlyWeather[]
  daily?: WeatherDay[]
  summary?: string
}
export interface Look {
  outfit_type: 'separates' | 'one_piece'
  top: string | null
  bottom: string | null
  one_piece: string | null
  outerwear: string | null
  shoes: string
  accessories: string[]
}
export interface Recommendation {
  date: string
  weather: Omit<
    WeatherDay,
    'precipitation_probability_max_percent' | 'precipitation_sum_mm' | 'wind_speed_max_m_s'
  > & {
    precipitation_probability_percent: number | null
    precipitation_mm: number | null
    wind_speed_m_s: number | null
  }
  best: Look
  worst: Look
  reasons: string[]
  avoid_reasons: string[]
  precautions: string[]
}
export interface OutfitResult {
  engine?: GenerationEngine
  generated_at: string | null
  fetched_at: string
  forecast_start_date?: string
  recommendation?: Recommendation
  daily?: Recommendation[]
  summary?: string
  wardrobe?: Record<
    'tops' | 'bottoms' | 'one_pieces' | 'outerwear' | 'shoes' | 'accessories',
    string[]
  >
  notice: string
  region: { code: string; name: string }
  personalization: Preferences & {
    generated_at: string | null
    adjustments: string[]
    llm_used: boolean
    engine?: GenerationEngine | null
  }
}

export interface GenerationEngine {
  provider: string
  model: string
  prompt_version: string
  generation_id?: string | null
}
export type GeneratedDay = Pick<
  Recommendation,
  'date' | 'best' | 'worst' | 'reasons' | 'avoid_reasons' | 'precautions'
>
export type FeedbackIssue =
  | 'clothing_category'
  | 'weather_logic'
  | 'explanation_mismatch'
  | 'preference_mismatch'
  | 'repetition'
  | 'other'
export type FeedbackStatus = 'reported' | 'draft' | 'approved' | 'rejected'
export interface FeedbackEdit {
  issues: FeedbackIssue[]
  note: string
  corrected_day: GeneratedDay | null
}
export interface FeedbackRecord extends FeedbackEdit {
  id: string
  generation_id: string
  date: string
  status: FeedbackStatus
  revision: number
  created_at: string
  updated_at: string
  reviewed_at: string | null
  reviewer_kind: null | 'user' | 'assistant'
  original_day: GeneratedDay | null
  weather: unknown
  preferences: unknown
  engine: Omit<GenerationEngine, 'generation_id'>
  checks: {
    errors: { code: string; message: string }[]
    warnings: { code: string; message: string }[]
  }
}
export const feedbackIssues: [FeedbackIssue, string][] = [
  ['clothing_category', '의류 구성'],
  ['weather_logic', '날씨 판단'],
  ['explanation_mismatch', '설명 불일치'],
  ['preference_mismatch', '취향 불일치'],
  ['repetition', '반복'],
  ['other', '기타'],
]

export function validateFeedbackEdit(edit: FeedbackEdit): string {
  if (!edit.issues.length) return '문제 유형을 하나 이상 선택해 주세요.'
  if (edit.note.length > 2000) return '문제 설명은 2,000자 이내로 작성해 주세요.'
  const day = edit.corrected_day
  if (!day) return ''
  for (const look of [day.best, day.worst]) {
    const required =
      look.outfit_type === 'one_piece'
        ? [look.one_piece, look.shoes]
        : [look.top, look.bottom, look.shoes]
    if (required.some((text) => !text?.trim())) return '의류 구성과 신발을 입력해 주세요.'
    const clothing = [
      look.top,
      look.bottom,
      look.one_piece,
      look.outerwear,
      look.shoes,
      ...look.accessories,
    ]
    if (clothing.some((text) => text !== null && (!text.trim() || text.trim().length > 200)))
      return '각 의류와 준비물은 1~200자로 작성해 주세요.'
    if (look.accessories.length > 10) return '준비물은 조합별로 10개까지 입력할 수 있어요.'
  }
  if (!day.reasons.length || !day.avoid_reasons.length)
    return '추천 이유와 피해야 할 이유를 각각 하나 이상 입력해 주세요.'
  if ([day.reasons, day.avoid_reasons, day.precautions].some((lines) => lines.length > 2))
    return '추천 이유·피해야 할 이유·주의 사항은 각각 두 줄까지 입력할 수 있어요.'
  if (
    [...day.reasons, ...day.avoid_reasons, ...day.precautions].some(
      (text) => !text.trim() || text.trim().length > 500,
    )
  )
    return '이유와 주의 사항은 항목마다 1~500자로 작성해 주세요.'
  return ''
}
