import { test, expect } from '@playwright/test'
import {
  mockApi,
  success,
  failure,
  outfit,
  weeklyOutfit,
  location,
  preferences,
} from './fixtures.js'

const baseId = '11111111-1111-4111-8111-111111111111'
const personalId = '22222222-2222-4222-8222-222222222222'
const clone = (value) => JSON.parse(JSON.stringify(value))
const day = ({ date, best, worst, reasons, avoid_reasons, precautions }) => ({
  date,
  best,
  worst,
  reasons,
  avoid_reasons,
  precautions,
})
function record(overrides = {}) {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    generation_id: baseId,
    date: outfit.recommendation.date,
    issues: ['weather_logic'],
    note: '테스트 신고',
    status: 'draft',
    revision: 1,
    created_at: '2026-11-08T01:00:00Z',
    updated_at: '2026-11-08T01:00:00Z',
    reviewed_at: null,
    reviewer_kind: null,
    original_day: day(outfit.recommendation),
    corrected_day: day(outfit.recommendation),
    weather: { server_weather: '서버 예보' },
    preferences: { server_preferences: true },
    engine: { provider: 'ollama', model: 'mock', prompt_version: 'test' },
    checks: { errors: [], warnings: [{ code: 'CAUTION', message: '기온을 확인해 주세요' }] },
    ...overrides,
  }
}
async function setup(page, options = {}) {
  const source = clone(outfit)
  source.engine.generation_id = options.missing ? null : baseId
  if (options.personal) {
    source.personalization.llm_used = true
    source.personalization.engine = {
      ...source.engine,
      generation_id: options.missingPersonal ? null : personalId,
    }
  }
  await mockApi(page, { outfitData: source })
  let signedIn = options.signedIn !== false
  await page.route('**/api/v1/users/**', (route) => {
    if (route.request().url().endsWith('/auth/logout')) {
      signedIn = false
      return route.fulfill({ json: success({ logged_out: true }) })
    }
    return route.fulfill(
      signedIn
        ? {
            json: success({
              user: { id: 'mock-owner', name: '테스트', email: 'synthetic@example.com' },
              profile: { location, preferences },
            }),
          }
        : { status: 401, json: failure('AUTH_REQUIRED', '로그인이 필요합니다.') },
    )
  })
  const state = { current: record(), calls: [], conflict: false, invalid: false, expire: false }
  await page.route('**/api/v1/outfit-feedback**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const body = request.method() === 'GET' ? null : request.postDataJSON()
    state.calls.push({
      path,
      query: url.searchParams.toString(),
      method: request.method(),
      body,
      headers: request.headers(),
    })
    if (state.expire)
      return route.fulfill({ status: 401, json: failure('AUTH_REQUIRED', '세션 만료') })
    if (path.endsWith('/export'))
      return route.fulfill({
        json: success({
          records: [
            { messages: [{ role: 'assistant', content: '검수된 답변' }] },
            { chosen: '수정', rejected: '원본' },
          ],
          count: 2,
          format: 'sft+preference',
        }),
      })
    if (request.method() !== 'GET' && state.conflict)
      return route.fulfill({ status: 409, json: failure('OUTFIT_FEEDBACK_CONFLICT', '버전 충돌') })
    if (request.method() === 'PUT' && state.invalid)
      return route.fulfill({
        status: 422,
        json: failure('OUTFIT_FEEDBACK_INVALID', '수정안 구성을 확인해 주세요.'),
      })
    if (request.method() === 'GET')
      return route.fulfill({
        json: success(
          path.endsWith('/outfit-feedback') ? { items: [state.current], total: 21 } : state.current,
        ),
      })
    if (path.endsWith('/approve') || path.endsWith('/reject'))
      state.current = {
        ...state.current,
        status: path.endsWith('/approve') ? 'approved' : 'rejected',
        revision: state.current.revision + 1,
        reviewer_kind: 'user',
      }
    else
      state.current = {
        ...state.current,
        ...body,
        status: body.corrected_day ? 'draft' : 'reported',
        revision: state.current.revision + 1,
      }
    return route.fulfill({ json: success(state.current) })
  })
  return state
}
async function detail(page) {
  await page.getByRole('button', { name: /테스트 신고/ }).click()
  await expect(page.getByRole('region', { name: '신고 상세' })).toBeVisible()
}

test('original weather summary is visible with Korean labels, units and zero values', async ({
  page,
}) => {
  const state = await setup(page)
  state.current.weather = {
    temperature_min_c: -3.5,
    temperature_max_c: 8,
    apparent_temperature_min_c: -6,
    apparent_temperature_max_c: 5.5,
    precipitation_probability_percent: 0,
    precipitation_mm: 0,
    wind_speed_m_s: 3.2,
  }
  await page.goto('./#review')
  await detail(page)
  const summary = page.getByRole('region', { name: '원본 답변에 사용한 날씨' })
  await expect(summary).toBeVisible()
  for (const [label, value] of [
    ['실제기온 최저~최고', '-3.5℃ ~ 8℃'],
    ['체감온도 최저~최고', '-6℃ ~ 5.5℃'],
    ['강수확률', '0%'],
    ['강수량', '0mm'],
    ['풍속', '3.2m/s'],
  ])
    await expect(
      summary.locator('dl > div').filter({ has: page.getByText(label, { exact: true }) }),
    ).toContainText(value)
  await expect(page.getByText('서버 원본 날씨·취향·생성 정보').locator('..')).not.toHaveAttribute(
    'open',
    '',
  )
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('weather summary marks null, missing and invalid values as unavailable without replacing valid bounds', async ({
  page,
}) => {
  const state = await setup(page)
  state.current.weather = {
    temperature_min_c: null,
    temperature_max_c: 12,
    apparent_temperature_max_c: 'unknown',
    precipitation_probability_percent: null,
    wind_speed_m_s: 0,
  }
  await page.goto('./#review')
  await detail(page)
  const summary = page.getByRole('region', { name: '원본 답변에 사용한 날씨' })
  await expect(summary).toContainText('정보 없음 ~ 12℃')
  await expect(summary).toContainText('정보 없음 ~ 정보 없음')
  await expect(summary.locator('dd')).toHaveText([
    '정보 없음 ~ 12℃',
    '정보 없음 ~ 정보 없음',
    '정보 없음',
    '정보 없음',
    '0m/s',
  ])
})

test('backend form limits prevent invalid submissions and keep the draft editable', async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto('./')
  await page.getByRole('button', { name: '답변 문제 신고·수정' }).click()
  await page.getByRole('button', { name: '문제 신고 저장' }).click()
  await expect(page.getByRole('alert')).toContainText('문제 유형을 하나 이상')
  expect(state.calls).toHaveLength(0)
  await expect(page.getByLabel('문제 설명')).toHaveAttribute('maxlength', '2000')
  await page.getByLabel('날씨 판단', { exact: true }).check()
  await page.getByLabel('직접 수정안 작성').check()
  await expect(page.getByLabel('추천 조합 신발', { exact: true })).toHaveAttribute(
    'maxlength',
    '200',
  )
  await page.getByLabel('추천 이유 (한 줄에 하나)', { exact: true }).fill('첫째\n둘째\n셋째')
  await page.getByRole('button', { name: '수정안 초안 저장' }).click()
  await expect(page.getByRole('alert')).toContainText('각각 두 줄까지')
  expect(state.calls).toHaveLength(0)
  await page.getByLabel('추천 이유 (한 줄에 하나)', { exact: true }).fill('정정된 이유')
  await page.getByRole('button', { name: '수정안 초안 저장' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(state.calls[0].body.corrected_day.reasons).toEqual(['정정된 이유'])
})

test('owner-only detail 404 uses the backend code without exposing another record', async ({
  page,
}) => {
  await setup(page)
  await page.route('**/outfit-feedback/33333333-3333-4333-8333-333333333333', (route) =>
    route.fulfill({
      status: 404,
      json: failure('OUTFIT_FEEDBACK_NOT_FOUND', '수정안을 찾을 수 없습니다.'),
    }),
  )
  await page.goto('./#review')
  await page.getByRole('button', { name: /테스트 신고/ }).click()
  await expect(page.getByRole('alert')).toHaveText('수정안을 찾을 수 없습니다.')
  await expect(page.getByRole('region', { name: '신고 상세' })).toHaveCount(0)
})

test('displayed answer report sends only server generation reference and correction fields', async ({
  page,
}) => {
  const state = await setup(page, { personal: true })
  await page.goto('./')
  await page.getByRole('button', { name: '답변 문제 신고·수정' }).click()
  await page.getByLabel('날씨 판단', { exact: true }).check()
  await page.getByLabel('문제 설명').fill('강수 판단 오류')
  await page.getByRole('button', { name: '문제 신고 저장' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const call = state.calls.find((c) => c.method === 'POST')
  expect(call.body).toEqual({
    generation_id: personalId,
    date: outfit.recommendation.date,
    issues: ['weather_logic'],
    note: '강수 판단 오류',
    corrected_day: null,
  })
  expect(call.headers['x-ondo-request']).toBe('1')
  expect(await page.evaluate(() => Object.keys(localStorage))).not.toContain('feedback')
})

test('weekly selection captures date and full correction without weather or forged originals', async ({
  page,
}) => {
  const state = await setup(page)
  await page.route('**/outfits/regions/**/weekly?**', (route) =>
    route.fulfill({
      json: success({ ...weeklyOutfit, engine: { ...outfit.engine, generation_id: baseId } }),
    }),
  )
  await page.goto('./')
  await page.getByRole('button', { name: '일주일', exact: true }).click()
  await page.locator('.day-button').nth(2).click()
  await page.getByRole('button', { name: '답변 문제 신고·수정' }).click()
  await page.getByLabel('날씨 판단', { exact: true }).check()
  await page.getByLabel('직접 수정안 작성').check()
  await page.getByLabel('추천 조합 구성', { exact: true }).selectOption('one_piece')
  await page.getByLabel('추천 조합 원피스', { exact: true }).fill('따뜻한 원피스')
  await page
    .getByLabel('추천 이유 (한 줄에 하나)', { exact: true })
    .fill('수정 이유 하나\n수정 이유 둘')
  await page.getByLabel('주의 사항 (한 줄에 하나)', { exact: true }).fill('수정된 주의 사항')
  await page.getByRole('button', { name: '수정안 초안 저장' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  const body = state.calls.find((c) => c.method === 'POST').body
  expect(body.date).toBe(weeklyOutfit.daily[2].date)
  expect(body.generation_id).toBe(baseId)
  expect(Object.keys(body.corrected_day).sort()).toEqual(
    ['date', 'best', 'worst', 'reasons', 'avoid_reasons', 'precautions'].sort(),
  )
  expect(body.corrected_day.best).toMatchObject({
    outfit_type: 'one_piece',
    top: null,
    bottom: null,
    one_piece: '따뜻한 원피스',
  })
  expect(body.corrected_day.worst).toEqual(weeklyOutfit.daily[2].worst)
  expect(body.corrected_day.reasons).toEqual(['수정 이유 하나', '수정 이유 둘'])
  expect(body).not.toHaveProperty('original_day')
})

for (const options of [{ missing: true }, { personal: true, missingPersonal: true }]) {
  test(`missing selected engine ID disables reporting ${JSON.stringify(options)}`, async ({
    page,
  }) => {
    const state = await setup(page, options)
    await page.goto('./')
    await expect(page.getByRole('button', { name: '답변 문제 신고·수정' })).toBeDisabled()
    await expect(
      page.getByText('이 답변에는 생성 기록 ID가 없어 신고·수정을 사용할 수 없어요.'),
    ).toBeVisible()
    expect(state.calls).toHaveLength(0)
  })
}

test('anonymous direct review hash requests no private records', async ({ page }) => {
  const state = await setup(page, { signedIn: false })
  await page.goto('./#review')
  await expect(page.getByLabel('비밀번호', { exact: true })).toBeVisible()
  expect(state.calls).toHaveLength(0)
  await page.evaluate(() => {
    window.location.hash = 'review'
  })
  await expect(page).toHaveURL(/#login$/)
  expect(state.calls).toHaveLength(0)
})

test('review saves draft separately then explicitly approves its current revision and exports JSONL', async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto('./#review')
  await expect(page.getByRole('heading', { name: '내 수정안 검수' })).toBeVisible()
  await detail(page)
  await page.getByText('서버 원본 날씨·취향·생성 정보').click()
  await expect(page.getByText(/server_weather/)).toContainText('서버 예보')
  await page.getByLabel('문제 설명').fill('직접 검토한 수정')
  await expect(page.getByRole('button', { name: '내 수정안 승인', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '초안 저장 (승인 해제)' }).click()
  await expect(page.getByRole('status').filter({ hasText: '초안을 저장했어요' })).toBeVisible()
  expect(state.calls.filter((c) => c.path.endsWith('/approve'))).toHaveLength(0)
  await page.getByRole('checkbox', { name: /내가 수정한 답변/ }).check()
  await page.getByRole('button', { name: '내 수정안 승인', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '내 수정안을 승인했어요' })).toBeVisible()
  const approval = state.calls.find((c) => c.path.endsWith('/approve'))
  expect(approval.body).toEqual({ revision: 2, confirmed: true })
  expect(approval.headers['x-ondo-request']).toBe('1')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '내 승인 데이터 JSONL 내보내기' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('ondo-my-reviewed-feedback.jsonl')
  const stream = await download.createReadStream()
  let contents = ''
  for await (const chunk of stream) contents += chunk.toString()
  const rows = contents
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line))
  expect(rows).toHaveLength(2)
  expect(rows[0].messages[0].content).toBe('검수된 답변')
  expect(rows[1]).toEqual({ chosen: '수정', rejected: '원본' })
})

test('409 preserves edits, requires explicit comparison, and rebases revision before saving', async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto('./#review')
  await detail(page)
  await page.getByLabel('문제 설명').fill('보존할 초안')
  state.conflict = true
  await page.getByRole('button', { name: '초안 저장 (승인 해제)' }).click()
  await expect(page.getByRole('alert')).toContainText('다시 불러온 뒤 비교')
  await expect(page.getByLabel('문제 설명')).toHaveValue('보존할 초안')
  await expect(page.getByRole('button', { name: '초안 저장 (승인 해제)' })).toBeDisabled()
  state.conflict = false
  state.current = { ...state.current, revision: 7, note: '서버 최신 설명' }
  await page.getByRole('button', { name: '최신 기록 다시 불러오기' }).click()
  await expect(page.getByRole('region', { name: '최신 기록 비교' })).toContainText('서버 최신 설명')
  await expect(page.getByLabel('문제 설명')).toHaveValue('보존할 초안')
  await page.getByRole('button', { name: '현재 입력을 최신 버전에 적용' }).click()
  await page.getByRole('button', { name: '초안 저장 (승인 해제)' }).click()
  await expect(page.getByRole('status').filter({ hasText: '초안을 저장했어요' })).toBeVisible()
  expect(state.calls.filter((c) => c.method === 'PUT').at(-1).body).toMatchObject({
    revision: 7,
    note: '보존할 초안',
  })
})

test('422 retains correction, server checks block approval, pagination and rejection use envelopes', async ({
  page,
}) => {
  const state = await setup(page)
  state.current.checks.errors.push({ code: 'INVALID_LOOK', message: '의류 조합 오류' })
  await page.goto('./#review')
  await detail(page)
  await expect(page.getByText('의류 조합 오류', { exact: true })).toBeVisible()
  await expect(page.getByText('기온을 확인해 주세요', { exact: true })).toBeVisible()
  await expect(page.getByText(/INVALID_LOOK|CAUTION/)).toHaveCount(0)
  await expect(page.getByRole('checkbox', { name: /내가 수정한 답변/ })).toBeDisabled()
  await page.getByLabel('추천 조합 신발', { exact: true }).fill('검증 전 신발')
  state.invalid = true
  await page.getByRole('button', { name: '초안 저장 (승인 해제)' }).click()
  await expect(page.getByText('수정안 구성을 확인해 주세요.')).toBeVisible()
  await expect(page.getByLabel('추천 조합 신발', { exact: true })).toHaveValue('검증 전 신발')
  state.invalid = false
  await page.getByRole('button', { name: '초안 저장 (승인 해제)' }).click()
  await expect(page.getByRole('status').filter({ hasText: '초안을 저장했어요' })).toBeVisible()
  await page.getByRole('button', { name: '내 수정안 거절' }).click()
  await expect(page.getByRole('status').filter({ hasText: '내 수정안을 거절했어요' })).toBeVisible()
  expect(state.calls.find((c) => c.path.endsWith('/reject')).body).toEqual({ revision: 2 })
  await page.getByRole('button', { name: '다음', exact: true }).click()
  await expect.poll(() => state.calls.some((c) => c.query.includes('offset=20'))).toBe(true)
  await page.getByLabel('상태', { exact: true }).selectOption('approved')
  await expect
    .poll(() =>
      state.calls.some((c) => c.query.includes('status=approved') && c.query.includes('offset=0')),
    )
    .toBe(true)
})

test('expired session removes private drafts and asks login', async ({ page }) => {
  const state = await setup(page)
  await page.goto('./#review')
  await detail(page)
  await page.getByLabel('문제 설명').fill('삭제할 비공개 초안')
  state.expire = true
  await page.getByRole('button', { name: '초안 저장 (승인 해제)' }).click()
  await expect(page).toHaveURL(/#login$/)
  await expect(page.getByText('삭제할 비공개 초안')).toHaveCount(0)
  await expect(page.getByText('세션이 만료되었어요. 다시 로그인해 주세요.')).toBeVisible()
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    '삭제할 비공개 초안',
  )
})

test('logout aborts late review detail without restoring private UI', async ({ page }) => {
  await setup(page)
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  let started = false
  await page.route('**/outfit-feedback/33333333-3333-4333-8333-333333333333', async (route) => {
    started = true
    await gate
    await route.fulfill({ json: success(record({ note: '지연된 비공개 기록' })) }).catch(() => {})
  })
  await page.goto('./#review')
  await page.getByRole('button', { name: /테스트 신고/ }).click()
  await expect.poll(() => started).toBe(true)
  await page.getByRole('button', { name: '로그아웃', exact: true }).click()
  release()
  await expect(page.getByRole('button', { name: /로그인 · 회원가입/ })).toBeVisible()
  await expect(page.getByText('지연된 비공개 기록')).toHaveCount(0)
  await page.evaluate(() => {
    window.location.hash = 'review'
  })
  await expect(page).toHaveURL(/#login$/)
})

test('account switch discards draft and ignores a late save response from the previous owner', async ({
  page,
}) => {
  const state = await setup(page)
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  let started = false
  await page.route('**/outfit-feedback/33333333-3333-4333-8333-333333333333', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback()
    started = true
    await gate
    await route
      .fulfill({ json: success(record({ note: '이전 계정의 지연 저장 결과' })) })
      .catch(() => {})
  })
  await page.goto('./#review')
  await detail(page)
  await page.getByLabel('문제 설명').fill('이전 계정 비공개 초안')
  await page.getByRole('button', { name: '초안 저장 (승인 해제)' }).click()
  await expect.poll(() => started).toBe(true)
  await page.evaluate(() => {
    window.location.hash = 'login'
  })
  await page.route('**/users/auth/login', (route) =>
    route.fulfill({
      json: success({
        user: { id: 'second-owner', name: '다른테스트', email: 'other@example.com' },
        profile: { location, preferences },
      }),
    }),
  )
  await page.getByLabel('이메일', { exact: true }).fill('other@example.com')
  await page.getByLabel('비밀번호', { exact: true }).fill('synthetic-password')
  await page.getByRole('button', { name: '로그인하기', exact: true }).click()
  await expect(page.getByRole('button', { name: '다른테스트 님' })).toBeVisible()
  release()
  state.current = record({ id: '44444444-4444-4444-8444-444444444444', note: '새 계정 신고' })
  await page.getByRole('button', { name: '내 수정안 검수', exact: true }).click()
  await expect(page.getByRole('button', { name: /새 계정 신고/ })).toBeVisible()
  await expect(page.getByText('이전 계정의 지연 저장 결과')).toHaveCount(0)
  await expect(page.getByLabel('문제 설명')).toHaveCount(0)
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    '이전 계정 비공개 초안',
  )
})

test('logout cancels delayed export before a private download is created', async ({ page }) => {
  await setup(page)
  let release
  const gate = new Promise((resolve) => {
    release = resolve
  })
  let started = false
  const downloads = []
  page.on('download', (download) => downloads.push(download))
  await page.route('**/outfit-feedback/export', async (route) => {
    started = true
    await gate
    await route
      .fulfill({
        json: success({ records: [{ private: true }], count: 1, format: 'sft+preference' }),
      })
      .catch(() => {})
  })
  await page.goto('./#review')
  await page.getByRole('button', { name: '내 승인 데이터 JSONL 내보내기' }).click()
  await expect.poll(() => started).toBe(true)
  await page.getByRole('button', { name: '로그아웃', exact: true }).click()
  release()
  await expect(page.getByRole('button', { name: /로그인 · 회원가입/ })).toBeVisible()
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  )
  expect(downloads).toHaveLength(0)
})

test('dialog close discards draft and review fits mobile with escaped server text', async ({
  page,
}) => {
  const state = await setup(page)
  await page.goto('./')
  await page.getByRole('button', { name: '답변 문제 신고·수정' }).click()
  await page.getByLabel('문제 설명').fill('저장하지 않을 내용')
  await page.getByRole('button', { name: '닫기', exact: true }).click()
  await page.getByRole('button', { name: '답변 문제 신고·수정' }).click()
  await expect(page.getByLabel('문제 설명')).toHaveValue('')
  await page.getByRole('button', { name: '닫기', exact: true }).click()
  state.current.original_day.best.top = '<img src=x onerror="window.injected=true">'
  await page.getByRole('button', { name: '내 수정안 검수', exact: true }).click()
  await detail(page)
  await expect(
    page.getByText('<img src=x onerror="window.injected=true">', { exact: true }),
  ).toBeVisible()
  expect(await page.evaluate(() => window.injected)).toBeUndefined()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})
