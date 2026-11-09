// 브라우저 시험 전용 합성 데이터. 운영 화면에는 주입하지 않는다.
const date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date())
export const dayAt = (offset = 0) =>
  new Date(new Date(`${date}T12:00:00+09:00`).getTime() + offset * 86400000)
    .toISOString()
    .slice(0, 10)
export const location = {
  id: 1835848,
  name: '서울',
  latitude: 37.5665,
  longitude: 126.978,
  country_code: 'KR',
  country: '대한민국',
  admin1: '서울특별시',
  admin2: null,
  timezone: 'Asia/Seoul',
}
export const busan = {
  ...location,
  id: 1838524,
  name: '부산',
  latitude: 35.1796,
  longitude: 129.0756,
  admin1: '부산광역시',
}
export const preferences = {
  cold_sensitivity: 'normal',
  style: 'default',
  activity: 'daily',
  clothing_preference: 'any',
  avoid_items: [],
}
export const look = {
  outfit_type: 'separates',
  top: '부드러운 코튼 셔츠',
  bottom: '베이지 코튼 팬츠',
  one_piece: null,
  outerwear: '가벼운 올리브 재킷',
  shoes: '편안한 스니커즈',
  accessories: ['가벼운 머플러'],
}
export const dayWeather = (offset = 0) => ({
  date: dayAt(offset),
  temperature_min_c: 9,
  temperature_max_c: 19,
  apparent_temperature_min_c: 8,
  apparent_temperature_max_c: 18,
  precipitation_probability_max_percent: 0,
  precipitation_sum_mm: 0,
  snowfall_sum_cm: 0,
  wind_speed_max_m_s: 2.4,
  uv_index_max: 3,
  temperature_range_c: 10,
  weather_code: 2,
  description: '구름 조금',
})
export const weather = {
  coordinates: { latitude: location.latitude, longitude: location.longitude },
  fetched_at: `${date}T10:00:00+09:00`,
  provider: 'Open-Meteo',
  source_url: 'https://open-meteo.com/',
  timezone: 'Asia/Seoul',
  units: {
    temperature: '°C',
    wind_speed: 'm/s',
    precipitation: 'mm',
    snowfall: 'cm',
    probability: '%',
  },
  current: {
    time: `${date}T10:00:00+09:00`,
    temperature_c: 17,
    apparent_temperature_c: 16,
    humidity_percent: 52,
    precipitation_mm: 0,
    wind_speed_m_s: 2.4,
    weather_code: 2,
    description: '구름 조금',
    is_day: true,
  },
  today: dayWeather(),
  summary: '아침저녁으로 선선하고, 한낮에는 포근한 하루예요. 최저 9℃, 최고 19℃가 예상됩니다.',
  hourly: Array.from({ length: 24 }, (_, hour) => ({
    time: `${date}T${String(hour).padStart(2, '0')}:00:00+09:00`,
    temperature_c: 10 + Math.round(8 * Math.sin((hour / 24) * Math.PI)),
    apparent_temperature_c: 9,
    precipitation_probability_percent: 0,
    wind_speed_m_s: 2,
    weather_code: hour < 12 ? 0 : 2,
    description: '구름 조금',
  })),
}
export const recommendation = (offset = 0) => ({
  date: dayAt(offset),
  weather: {
    ...dayWeather(offset),
    precipitation_probability_percent: 0,
    precipitation_mm: 0,
    snowfall_cm: 0,
    wind_speed_m_s: 2.4,
    uv_index: 3,
  },
  temperature_basis: 'apparent_temperature',
  reference_temperature_c: 18,
  best: look,
  worst: {
    ...look,
    top: '얇은 반팔 티셔츠',
    outerwear: null,
    bottom: '짧은 반바지',
    shoes: '샌들',
  },
  reasons: [
    '선선한 아침에는 재킷을 걸치고, 낮에는 가볍게 벗어 온도를 조절해 보세요.',
    '편안한 면 소재와 스니커즈로 일상에서 부담 없이 입기 좋은 조합이에요.',
  ],
  avoid_reasons: ['아침저녁에는 얇은 반팔과 반바지만 입으면 쌀쌀할 수 있어요.'],
  precautions: ['아침과 낮의 기온 차이가 있어요. 가벼운 겉옷을 챙겨 주세요.'],
})
export const outfit = {
  ...weather,
  generated_at: `${date}T09:50:00+09:00`,
  base_version: 'fixture',
  engine: {
    provider: 'ollama',
    model: 'test-only',
    prompt_version: 'test',
    fallback_used: false,
    fallback_reason: null,
  },
  notice: '날씨 기반의 일반적인 참고 추천입니다. 개인의 체감과 실제 예보에 맞춰 조절하세요.',
  region: {
    code: '11140',
    name: '서울특별시 중구',
    latitude: location.latitude,
    longitude: location.longitude,
    source: 'VWorld LT_C_ADSIGG_INFO',
  },
  location,
  recommendation: recommendation(),
  personalization: {
    ...preferences,
    generated_at: null,
    adjustments: [],
    llm_used: false,
    cache_hit: false,
    version: null,
    engine: null,
  },
}
export const weeklyWeather = {
  coordinates: weather.coordinates,
  fetched_at: weather.fetched_at,
  provider: weather.provider,
  source_url: weather.source_url,
  timezone: weather.timezone,
  units: weather.units,
  daily: Array.from({ length: 7 }, (_, i) => dayWeather(i)),
}
export const weeklyOutfit = {
  ...outfit,
  forecast_start_date: date,
  daily: Array.from({ length: 7 }, (_, i) => recommendation(i)),
  wardrobe: {
    tops: ['코튼 셔츠'],
    bottoms: ['면바지'],
    outerwear: ['재킷'],
    shoes: ['스니커즈'],
    one_pieces: [],
    accessories: ['머플러'],
  },
  summary: '큰 일교차에 대비해 가벼운 겉옷을 준비하세요.',
}
export const success = (data) => ({
  code: 'SUCCESS',
  message: '요청이 성공했습니다.',
  data,
  details: [],
})
export const failure = (code, message) => ({ code, message, data: null, details: [] })

export async function mockApi(
  page,
  { weeklyReady = true, outfitStatus = 200, outfitData = outfit } = {},
) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/v1/users/me')
      return route.fulfill({ status: 401, json: failure('AUTH_REQUIRED', '로그인이 필요합니다.') })
    if (path.endsWith('/weather/locations'))
      return route.fulfill({
        json: success({
          locations: url.searchParams.get('query') === '없는동네' ? [] : [location, busan],
          attribution: 'GeoNames · Open-Meteo',
        }),
      })
    if (path.endsWith('/weather/today')) return route.fulfill({ json: success(weather) })
    if (path.endsWith('/weather/weekly')) return route.fulfill({ json: success(weeklyWeather) })
    if (path.includes('/outfits/regions/')) {
      if (outfitStatus !== 200)
        return route.fulfill({
          status: outfitStatus,
          json: failure('OUTFIT_LLM_UNAVAILABLE', '추천 서버에 연결하지 못했습니다.'),
        })
      if (path.endsWith('/weekly'))
        return route.fulfill({
          status: weeklyReady ? 200 : 503,
          json: weeklyReady
            ? success(weeklyOutfit)
            : failure('OUTFIT_WEEKLY_NOT_READY', '주간 추천 준비 전입니다.'),
        })
      return route.fulfill({ json: success(outfitData) })
    }
    return route.fulfill({ status: 404, json: failure('NOT_FOUND', '찾을 수 없습니다.') })
  })
}

export async function seed(page, selected = location) {
  await page.addInitScript(
    ({ location, preferences }) =>
      localStorage.setItem('ondo.settings.v1', JSON.stringify({ location, preferences })),
    { location: selected, preferences },
  )
}
