import { test, expect } from '@playwright/test'
import {
  mockApi,
  seed,
  success,
  failure,
  location,
  outfit,
  weather,
  dayAt,
  weeklyOutfit,
  recommendation,
} from './fixtures.js'

test('첫 방문에는 데이터 생성 없이 지역 선택부터 안내한다', async ({ page }) => {
  await mockApi(page)
  const requests = []
  page.on('request', (req) => {
    if (req.url().includes('/api/') && !req.url().includes('/users/me')) requests.push(req.url())
  })
  await page.goto('./')
  await expect(page.getByRole('heading', { name: /날씨를 알면/ })).toBeVisible()
  await page.getByRole('button', { name: '우리 동네 찾아보기' }).click()
  await expect(page.getByRole('searchbox', { name: '지역명' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  expect(requests).toEqual([])
})

test('지역 검색·선택으로 실제 계약의 날씨와 추천을 함께 표시한다', async ({ page }) => {
  await mockApi(page)
  await page.goto('./')
  await page.getByRole('button', { name: '내 지역 선택' }).click()
  await page.getByRole('searchbox', { name: '지역명' }).fill('서울')
  await page.getByRole('button', { name: /서울 서울특별시/ }).click()
  await expect(page.locator('.current-temperature')).toHaveText('17°')
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
  await expect(page.locator('.weather-metrics')).toContainText('0%')
  await expect(page.locator('.weather-metrics')).toContainText('52%')
  await page.getByRole('button', { name: '이런 옷차림은 피하는 게 좋아요' }).click()
  await expect(page.getByText('얇은 반팔 티셔츠', { exact: true })).toBeVisible()
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('ondo.settings.v1')))
  expect(saved.location.id).toBe(location.id)
  await page.reload()
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
})

test('옷 추천이 느려도 날씨를 먼저 제공하고 같은 요청을 중복 전송하지 않는다', async ({ page }) => {
  await seed(page)
  await mockApi(page)
  let finish
  const wait = new Promise((resolve) => {
    finish = resolve
  })
  let calls = 0
  await page.route('**/outfits/regions/**', async (route) => {
    calls++
    await wait
    await route.fulfill({ json: success(outfit) }).catch(() => {})
  })
  await page.goto('./')
  await expect(page.locator('.current-temperature')).toHaveText('17°')
  await expect(page.getByRole('heading', { name: '오늘의 한 벌을 고르고 있어요.' })).toBeVisible()
  expect(calls).toBe(1)
  finish()
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
})

test('주간 미준비 응답은 장애 대신 준비 안내를 표시하고 날씨는 유지한다', async ({ page }) => {
  await seed(page)
  await mockApi(page, { weeklyReady: false })
  await page.goto('./')
  await page.getByRole('button', { name: '일주일', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '일주일의 옷장을 준비하고 있어요.' }),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: '준비 상태 다시 확인' })).toBeVisible()
  await expect(page.locator('.day-button')).toHaveCount(7)
  await expect(page.locator('.current-temperature')).toHaveText('19°')
})

test('주간 날짜별 추천과 원피스·준비 의류를 표시한다', async ({ page }) => {
  await seed(page)
  await mockApi(page)
  await page.goto('./')
  await page.getByRole('button', { name: '일주일', exact: true }).click()
  await expect(page.locator('.day-button')).toHaveCount(7)
  await page.locator('.day-button').nth(2).click()
  await expect(page.locator('.day-button').nth(2)).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('heading', { name: '이번 주, 옷장에 준비해요.' })).toBeVisible()
  await expect(page.locator('.wardrobe-panel')).toContainText('코튼 셔츠')
  await expect(page.locator('.recommendation-region')).toContainText('서울특별시 중구')
  await expect(page.locator('#outfit-title')).toContainText(`${Number(dayAt(2).slice(8))}일`)
})

test('주간 최신 날씨에 장애가 있어도 저장된 날짜별 추천은 조회한다', async ({ page }) => {
  await seed(page)
  await mockApi(page)
  await page.route('**/weather/weekly?**', (route) =>
    route.fulfill({ status: 503, json: failure('WEATHER_UNAVAILABLE', '날씨 연결 실패') }),
  )
  await page.goto('./')
  await page.getByRole('button', { name: '일주일', exact: true }).click()
  await expect(page.getByRole('heading', { name: '날씨를 불러오지 못했어요' })).toBeVisible()
  await expect(page.locator('.day-button')).toHaveCount(7)
  await page.locator('.day-button').nth(2).click()
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
  await expect(page.locator('.day-button').nth(2)).toHaveAttribute('aria-pressed', 'true')
})

test('이전 배치의 주간 추천은 배열 순서가 아니라 날짜로 연결한다', async ({ page }) => {
  await seed(page)
  await mockApi(page)
  const older = {
    ...weeklyOutfit,
    forecast_start_date: dayAt(-1),
    daily: Array.from({ length: 7 }, (_, i) => {
      const day = recommendation(i - 1)
      return {
        ...day,
        best: {
          ...day.best,
          top: i === 0 ? '어제의 셔츠' : i === 1 ? '오늘의 셔츠' : '다른 날의 셔츠',
        },
      }
    }),
  }
  await page.route('**/outfits/regions/**/weekly?**', (route) =>
    route.fulfill({ json: success(older) }),
  )
  await page.goto('./')
  await page.getByRole('button', { name: '일주일', exact: true }).click()
  await expect(page.getByText('오늘의 셔츠', { exact: true })).toBeVisible()
  await expect(page.getByText('어제의 셔츠', { exact: true })).not.toBeVisible()
  await expect(page.locator('.inline-notice')).toContainText('예보 기준 추천')
  await page.locator('.day-button').last().click()
  await expect(page.getByRole('heading', { name: '선택한 날짜의 추천이 없어요.' })).toBeVisible()
})

test('개인 취향은 적용할 때 한 번만 요청에 전달하고 날씨는 재조회하지 않는다', async ({ page }) => {
  await seed(page)
  await mockApi(page)
  const calls = []
  page.on('request', (req) => {
    if (req.url().includes('/api/')) calls.push(req.url())
  })
  await page.goto('./')
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '내 취향 설정' }).click()
  await page.getByRole('radio', { name: '추위를 타요' }).check()
  await page.getByRole('radio', { name: '단정하게' }).check()
  expect(calls.filter((url) => url.includes('/outfits/'))).toHaveLength(1)
  await page.getByRole('button', { name: '내 취향 반영하기' }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await expect(page.locator('.small-label')).toContainText('취향을 더한 추천')
  expect(calls.filter((url) => url.includes('/weather/'))).toHaveLength(1)
  expect(calls.filter((url) => url.includes('/outfits/'))).toHaveLength(2)
  const request = new URL(calls.filter((url) => url.includes('/outfits/')).at(-1))
  expect(request.searchParams.get('cold_sensitivity')).toBe('cold')
  expect(request.searchParams.get('style')).toBe('formal')
  expect(request.searchParams.get('activity')).toBe('daily')
})

test('추천 오류를 숨기지 않으며 명시적으로 재시도할 수 있다', async ({ page }) => {
  await seed(page)
  await mockApi(page, { outfitStatus: 503 })
  await page.goto('./')
  await expect(page.getByRole('heading', { name: '추천을 잠시 불러오지 못했어요.' })).toBeVisible()
  await expect(page.locator('.current-temperature')).toHaveText('17°')
  await page.route('**/outfits/regions/**', (route) => route.fulfill({ json: success(outfit) }))
  await page.getByRole('button', { name: '추천 다시 불러오기' }).click()
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
})

test('원피스의 null 상하의와 누락된 날씨를 올바르게 표시한다', async ({ page }) => {
  await seed(page)
  await mockApi(page, {
    outfitData: {
      ...outfit,
      recommendation: {
        ...outfit.recommendation,
        best: {
          ...outfit.recommendation.best,
          outfit_type: 'one_piece',
          top: null,
          bottom: null,
          one_piece: '긴소매 코튼 원피스',
          outerwear: null,
        },
      },
    },
  })
  await page.route('**/weather/today?**', (route) =>
    route.fulfill({
      json: success({
        ...weather,
        current: {
          ...weather.current,
          humidity_percent: null,
          wind_speed_m_s: null,
          apparent_temperature_c: null,
        },
        today: { ...weather.today, precipitation_probability_max_percent: null },
      }),
    }),
  )
  await page.goto('./')
  await expect(page.getByText('긴소매 코튼 원피스', { exact: true })).toBeVisible()
  await expect(page.locator('.clothing-list dt')).toHaveText(['원피스', '신발', '준비물'])
  await expect(page.locator('.weather-metrics')).not.toContainText('null')
  await expect(page.locator('.weather-metrics')).toContainText('정보 없음')
  await expect(page.locator('.feels-like')).toHaveText('체감 —')
})

test('검색 결과가 없거나 조회에 실패하면 다시 검색할 수 있다', async ({ page }) => {
  await mockApi(page)
  await page.goto('./')
  await page.getByRole('button', { name: '내 지역 선택' }).click()
  await page.getByRole('searchbox', { name: '지역명' }).fill('없는동네')
  await expect(page.getByText('검색 결과가 없어요.', { exact: false })).toBeVisible()
  await page.route('**/weather/locations?**', (route) =>
    route.fulfill({
      status: 503,
      json: failure('WEATHER_UNAVAILABLE', '지역 검색을 잠시 사용할 수 없습니다.'),
    }),
  )
  await page.getByRole('searchbox', { name: '지역명' }).fill('부산')
  await expect(page.getByRole('button', { name: '다시 검색' })).toBeVisible()
})

test('손상된 저장값이 있어도 첫 화면을 사용할 수 있다', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('ondo.settings.v1', '{broken-json'))
  await page.goto('./')
  await expect(page.getByRole('button', { name: '우리 동네 찾아보기' })).toBeVisible()
})

test('지역을 바꾸면 이전 지역의 늦은 응답이 현재 추천을 덮어쓰지 않는다', async ({ page }) => {
  await seed(page)
  await mockApi(page)
  let release
  const delayed = new Promise((resolve) => {
    release = resolve
  })
  await page.route('**/outfits/regions/**', async (route) => {
    const old = route.request().url().includes(String(location.id))
    if (old) await delayed
    const result = old
      ? outfit
      : {
          ...outfit,
          region: { ...outfit.region, name: '부산광역시 중구' },
          recommendation: {
            ...outfit.recommendation,
            best: { ...outfit.recommendation.best, top: '부산의 셔츠' },
          },
        }
    await route.fulfill({ json: success(result) }).catch(() => {})
  })
  await page.goto('./')
  await page.getByRole('button', { name: '서울', exact: true }).click()
  await page.getByRole('searchbox', { name: '지역명' }).fill('부산')
  await page.getByRole('button', { name: /부산 부산광역시/ }).click()
  await expect(page.getByText('부산의 셔츠', { exact: true })).toBeVisible()
  release()
  await expect(page.locator('.recommendation-region')).toContainText('부산광역시 중구')
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).not.toBeVisible()
})

test('화면 넘침과 브라우저 오류 없이 데스크톱·모바일에서 사용한다', async ({ page }, testInfo) => {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await seed(page)
  await mockApi(page)
  await page.goto('./')
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({ path: testInfo.outputPath('today.png'), fullPage: true })
  await page.getByRole('button', { name: '일주일', exact: true }).click()
  await expect(page.locator('.day-button')).toHaveCount(7)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({ path: testInfo.outputPath('weekly.png'), fullPage: true })
  expect(errors).toEqual([])
})
