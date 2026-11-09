import type {
  Account,
  FeedbackRecord,
  FeedbackEdit,
  FeedbackStatus,
  ProfileInput,
  Location,
  OutfitResult,
  Period,
  Preferences,
  WeatherResult,
} from './types'

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status?: number,
  ) {
    super(message)
  }
}

async function request<T>(
  path: string,
  signal: AbortSignal,
  timeout: number,
  init: RequestInit = {},
): Promise<T> {
  const controller = new AbortController()
  const cancel = () => controller.abort()
  signal.addEventListener('abort', cancel, { once: true })
  if (signal.aborted) controller.abort()
  let timedOut = false
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeout)
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...init,
      credentials: 'same-origin',
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init.method && init.method !== 'GET' ? { 'X-Ondo-Request': '1' } : {}),
      },
    })
    const body = await response.json().catch(() => null)
    if (!response.ok || body?.code !== 'SUCCESS' || body?.data == null) {
      throw new ApiError(
        body?.code || 'INVALID_RESPONSE',
        body?.message || '서버 응답을 확인하지 못했어요. 잠시 후 다시 시도해 주세요.',
        response.status,
      )
    }
    return body.data as T
  } catch (error) {
    if (signal.aborted) throw new DOMException('요청 취소', 'AbortError')
    if (timedOut)
      throw new ApiError(
        'CLIENT_TIMEOUT',
        '응답을 기다리는 시간이 길어졌어요. 잠시 후 다시 확인해 주세요.',
      )
    if (error instanceof ApiError) throw error
    throw new ApiError(
      'NETWORK_ERROR',
      '서버에 연결하지 못했어요. 연결 상태를 확인하고 다시 시도해 주세요.',
    )
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', cancel)
  }
}

export const searchLocations = (query: string, signal: AbortSignal, offset = 0) =>
  request<{ locations: Location[]; attribution: string; total: number; has_more: boolean }>(
    `/weather/locations?${new URLSearchParams({ query, limit: '20', offset: String(offset) })}`,
    signal,
    20_000,
  )

export const getWeather = (location: Location, period: Period, signal: AbortSignal) =>
  request<WeatherResult>(
    `/weather/${period}?${new URLSearchParams({ latitude: String(location.latitude), longitude: String(location.longitude) })}`,
    signal,
    65_000,
  )

export const getOutfit = (
  location: Location,
  period: Period,
  preferences: Preferences,
  signal: AbortSignal,
) => {
  const query = new URLSearchParams({
    cold_sensitivity: preferences.cold_sensitivity,
    style: preferences.style,
    activity: preferences.activity,
    clothing_preference: preferences.clothing_preference,
  })
  for (const item of [...preferences.avoid_items].sort()) query.append('avoid_items', item)
  // 최초 개인화는 공통·개인 생성을 연달아 기다릴 수 있다. 중복 요청이나 자동 재시도는 하지 않는다.
  return request<OutfitResult>(
    `/outfits/regions/${location.id}/${period}?${query}`,
    signal,
    600_000,
  )
}

export const getAccount = (signal: AbortSignal) => request<Account>('/users/me', signal, 20_000)
export const authenticate = (
  mode: 'login' | 'register',
  values: { email: string; password: string; name?: string },
  signal: AbortSignal,
) =>
  request<Account>(`/users/auth/${mode}`, signal, 30_000, {
    method: 'POST',
    body: JSON.stringify(values),
  })
export const updateProfile = (values: ProfileInput, signal: AbortSignal) =>
  request<Account>('/users/me/profile', signal, 20_000, {
    method: 'PUT',
    body: JSON.stringify(values),
  })
export const logoutAccount = (signal: AbortSignal) =>
  request<{ logged_out: boolean }>('/users/auth/logout', signal, 20_000, { method: 'POST' })

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return '데이터를 불러오지 못했어요. 다시 시도해 주세요.'
  if (error.code === 'OUTFIT_WEEKLY_NOT_READY')
    return '이번 주 추천을 준비하고 있어요. 매일 새벽 1~2시 사이 시작하는 준비 작업이 끝나면 확인할 수 있어요. 처음 선택한 지역이나 취향은 다음 작업에 반영돼요.'
  if (error.code === 'WEATHER_REGION_NOT_CONFIGURED')
    return '이 지역의 추천을 연결하지 못했어요. 지역 서비스 설정을 확인해야 해요. 날씨는 계속 확인할 수 있어요.'
  if (error.code === 'OUTFIT_LLM_NOT_CONFIGURED' || error.code === 'OUTFIT_LLM_MODEL_NOT_FOUND')
    return '옷차림 추천 서비스를 준비하고 있어요. 잠시 후 다시 확인해 주세요.'
  return error.message
}

const feedbackPath = '/outfit-feedback'
export const createFeedback = (
  values: FeedbackEdit & { generation_id: string; date: string },
  signal: AbortSignal,
) =>
  request<FeedbackRecord>(feedbackPath, signal, 20_000, {
    method: 'POST',
    body: JSON.stringify(values),
  })
export const listFeedback = (status: FeedbackStatus | '', offset: number, signal: AbortSignal) =>
  request<{ items: FeedbackRecord[]; total: number }>(
    `${feedbackPath}?${new URLSearchParams({ ...(status ? { status } : {}), limit: '20', offset: String(offset) })}`,
    signal,
    20_000,
  )
export const getFeedback = (id: string, signal: AbortSignal) =>
  request<FeedbackRecord>(`${feedbackPath}/${encodeURIComponent(id)}`, signal, 20_000)
export const updateFeedback = (
  id: string,
  values: FeedbackEdit & { revision: number },
  signal: AbortSignal,
) =>
  request<FeedbackRecord>(`${feedbackPath}/${encodeURIComponent(id)}`, signal, 20_000, {
    method: 'PUT',
    body: JSON.stringify(values),
  })
export const reviewFeedback = (
  id: string,
  revision: number,
  action: 'approve' | 'reject',
  signal: AbortSignal,
) =>
  request<FeedbackRecord>(`${feedbackPath}/${encodeURIComponent(id)}/${action}`, signal, 20_000, {
    method: 'POST',
    body: JSON.stringify({ revision, ...(action === 'approve' ? { confirmed: true } : {}) }),
  })
export const exportFeedback = (signal: AbortSignal) =>
  request<{ records: object[]; count: number; format: 'sft+preference' }>(
    `${feedbackPath}/export`,
    signal,
    30_000,
  )
export function feedbackError(cause: unknown): string {
  if (cause instanceof ApiError && cause.status === 409)
    return '다른 변경 사항이 있어요. 현재 수정 내용은 유지했어요. 다시 불러온 뒤 비교해 주세요.'
  if (cause instanceof ApiError && cause.status === 401)
    return '세션이 만료되었어요. 다시 로그인해 주세요.'
  return errorMessage(cause)
}
