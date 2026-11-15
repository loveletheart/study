import { test, expect } from '@playwright/test'
import { mockApi, success, failure, preferences, location, busan, seed } from './fixtures.js'

const password = 'test-password-123'
const user = {
  id: '01a83ce4-6d0b-4fcb-800e-bc9bf0ee59b1',
  name: '온도친구',
  email: 'user@example.com',
}

async function mockAccount(page, { signedIn = false, profileReady = false } = {}) {
  await mockApi(page)
  const state = {
    signedIn,
    failSave: false,
    expired: false,
    calls: [],
    current: {
      user,
      profile: {
        location: profileReady ? location : null,
        preferences: { ...preferences, avoid_items: [] },
      },
    },
  }
  await page.route('**/api/v1/users/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const values = request.method() === 'GET' ? null : request.postDataJSON()
    state.calls.push({ path, method: request.method(), values, headers: request.headers() })
    if (path.endsWith('/auth/login') || path.endsWith('/auth/register')) {
      if (values.password !== password)
        return route.fulfill({
          status: 401,
          json: failure('AUTH_INVALID_CREDENTIALS', '이메일 또는 비밀번호를 확인해 주세요.'),
        })
      state.signedIn = true
      state.expired = false
      if (values.name) state.current.user = { ...user, name: values.name }
      return route.fulfill({
        status: path.endsWith('/register') ? 201 : 200,
        headers: {
          'Set-Cookie': 'ondo_session=browser-test-session; HttpOnly; SameSite=Lax; Path=/api/v1',
        },
        json: success(state.current),
      })
    }
    if (path.endsWith('/auth/logout')) {
      state.signedIn = false
      return route.fulfill({
        headers: { 'Set-Cookie': 'ondo_session=; Max-Age=0; Path=/api/v1' },
        json: success({ logged_out: true }),
      })
    }
    if (!state.signedIn || state.expired)
      return route.fulfill({
        status: 401,
        json: failure('AUTH_REQUIRED', '로그인이 필요합니다. 다시 로그인해 주세요.'),
      })
    if (path.endsWith('/me/profile')) {
      if (state.failSave)
        return route.fulfill({
          status: 500,
          json: failure('COMMON_INTERNAL_ERROR', '저장에 실패했어요. 다시 시도해 주세요.'),
        })
      state.current = {
        user: { ...state.current.user, name: values.name },
        profile: {
          location:
            values.location_id === location.id
              ? location
              : values.location_id === busan.id
                ? busan
                : null,
          preferences: values.preferences,
        },
      }
    }
    return route.fulfill({ json: success(state.current) })
  })
  return state
}

async function openSignup(page) {
  await page.goto('./#signup')
  await page.getByRole('textbox', { name: '닉네임', exact: true }).fill('온도친구')
  await page.getByRole('textbox', { name: '이메일', exact: true }).fill(user.email)
  await page.getByLabel('비밀번호', { exact: true }).fill(password)
  await page.getByLabel('비밀번호 확인', { exact: true }).fill(password)
}

test('회원가입 비밀번호가 다르면 전송 전에 안내한다', async ({ page }, testInfo) => {
  const state = await mockAccount(page)
  await openSignup(page)
  await page.getByLabel('비밀번호 확인', { exact: true }).fill('different-password')
  await page.getByRole('button', { name: '가입하고 취향 설정하기' }).click()
  await expect(page.getByRole('alert')).toContainText('비밀번호가 서로 달라요')
  expect(state.calls.filter((call) => call.method === 'POST')).toHaveLength(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({ path: testInfo.outputPath('signup.png'), fullPage: true })
})

test('회원가입 후 지역과 추가 취향을 저장하고 추천 요청에 반영한다', async ({ page }, testInfo) => {
  const state = await mockAccount(page)
  const outfits = []
  page.on('request', (request) => {
    if (request.url().includes('/outfits/')) outfits.push(new URL(request.url()))
  })
  await openSignup(page)
  await page.getByRole('button', { name: '가입하고 취향 설정하기' }).click()
  await expect(page.getByRole('heading', { name: '먼저, 당신의 하루를 알려주세요.' })).toBeVisible()
  await page.getByRole('button', { name: '우리 동네 찾아보기' }).click()
  await page.getByRole('searchbox', { name: '지역명' }).fill('서울')
  await page.getByRole('button', { name: /서울 서울특별시/ }).click()
  await page.getByRole('radio', { name: '추위를 타요' }).check()
  await page.getByRole('radio', { name: '단정하게' }).check()
  await page.getByRole('radio', { name: '야외활동' }).check()
  await page.getByRole('radio', { name: '남성복 위주' }).check()
  await page.getByRole('checkbox', { name: '반바지', exact: true }).check()
  await page.getByRole('checkbox', { name: '샌들', exact: true }).check()
  expect(outfits).toHaveLength(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({ path: testInfo.outputPath('profile.png'), fullPage: true })
  await page.getByRole('button', { name: '저장하고 나의 추천 보기' }).click()
  await expect(page.getByRole('button', { name: '온도친구 님' })).toBeVisible()
  await expect(page.getByText('부드러운 코튼 셔츠', { exact: true })).toBeVisible()
  const saved = state.calls.find((call) => call.path.endsWith('/me/profile'))
  expect(saved.values.location_id).toBe(location.id)
  expect(saved.values.preferences).toMatchObject({
    cold_sensitivity: 'cold',
    style: 'formal',
    activity: 'outdoor',
    clothing_preference: 'menswear',
    avoid_items: ['sandals', 'shorts'],
  })
  expect(saved.headers['x-ondo-request']).toBe('1')
  expect(outfits).toHaveLength(1)
  expect(outfits[0].searchParams.get('clothing_preference')).toBe('menswear')
  expect(outfits[0].searchParams.getAll('avoid_items')).toEqual(['sandals', 'shorts'])
  const browserStorage = await page.evaluate(() => JSON.stringify(localStorage))
  expect(browserStorage).not.toContain(password)
  expect(browserStorage).not.toContain(user.email)
  expect(await page.evaluate(() => document.cookie)).not.toContain('ondo_session')
})

test('로그인한 프로필을 복원하고 로그아웃하면 계정 데이터를 화면에서 제거한다', async ({
  page,
}) => {
  await seed(page, busan)
  const state = await mockAccount(page, { profileReady: true })
  state.current.profile.preferences = {
    ...preferences,
    style: 'formal',
    clothing_preference: 'womenswear',
    avoid_items: ['heels'],
  }
  await page.goto('./#login')
  await page.getByRole('textbox', { name: '이메일', exact: true }).fill(user.email)
  await page.getByLabel('비밀번호', { exact: true }).fill(password)
  await page.getByRole('button', { name: '로그인하기' }).click()
  await expect(page.getByRole('button', { name: '온도친구 님' })).toBeVisible()
  await expect(page.getByRole('button', { name: '서울', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: '온도친구 님' })).toBeVisible()
  await page.getByRole('button', { name: '로그아웃', exact: true }).click()
  await expect(page.getByRole('button', { name: '로그인 · 회원가입' })).toBeVisible()
  await expect(page.getByRole('button', { name: '부산', exact: true })).toBeVisible()
  await expect(page.getByText('온도친구 님', { exact: true })).not.toBeVisible()
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('ondo.settings.v1')))
  expect(stored.location.id).toBe(busan.id)
  expect(stored.preferences.style).toBe('default')
})

test('잘못된 로그인은 오류를 표시하고 재입력할 수 있다', async ({ page }) => {
  await mockAccount(page)
  await page.goto('./#login')
  await page.getByRole('textbox', { name: '이메일', exact: true }).fill(user.email)
  await page.getByLabel('비밀번호', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '로그인하기' }).click()
  await expect(page.getByRole('alert')).toContainText('이메일 또는 비밀번호')
  await page.getByLabel('비밀번호', { exact: true }).fill(password)
  await page.getByRole('button', { name: '로그인하기' }).click()
  await expect(page.getByRole('heading', { name: '먼저, 당신의 하루를 알려주세요.' })).toBeVisible()
})

test('저장한 지역이 없는 계정은 기본 지역을 표시하고 취향만 저장할 수 있다', async ({ page }) => {
  const state = await mockAccount(page, { signedIn: true })
  await page.goto('./')
  await expect(page.locator('.toolbar-caption')).toHaveText('기본 지역 · 서울특별시 중구')
  expect(state.calls.filter((call) => call.method === 'PUT')).toHaveLength(0)
  await page.getByRole('button', { name: '내 취향 설정' }).click()
  await page.getByRole('radio', { name: '추위를 타요' }).check()
  await page.getByRole('button', { name: '내 취향 반영하기' }).click()
  await expect(page.getByRole('dialog')).not.toBeVisible()
  expect(state.calls.find((call) => call.method === 'PUT').values.location_id).toBeNull()
  await expect(page.locator('.toolbar-caption')).toHaveText('기본 지역 · 서울특별시 중구')
})

test('프로필 저장 실패는 초안을 유지하고 재시도 성공 후에만 적용한다', async ({ page }) => {
  const state = await mockAccount(page, { signedIn: true, profileReady: true })
  state.failSave = true
  await page.goto('./#profile')
  await page.getByRole('radio', { name: '편안하게' }).check()
  await page.getByRole('checkbox', { name: '원피스', exact: true }).check()
  await page.getByRole('button', { name: '저장하고 나의 추천 보기' }).click()
  await expect(page.getByRole('alert')).toContainText('저장에 실패')
  await expect(page.getByRole('radio', { name: '편안하게' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: '원피스', exact: true })).toBeChecked()
  state.failSave = false
  await page.getByRole('button', { name: '저장하고 나의 추천 보기' }).click()
  await expect(page.locator('.success-notice')).toContainText('저장했어요')
  expect(state.current.profile.preferences.style).toBe('casual')
})

test('세션이 만료되면 프로필을 덮어쓰지 않고 재로그인을 안내한다', async ({ page }) => {
  const state = await mockAccount(page, { signedIn: true, profileReady: true })
  await page.goto('./#profile')
  await page.getByRole('radio', { name: '편안하게' }).check()
  state.expired = true
  await page.getByRole('button', { name: '저장하고 나의 추천 보기' }).click()
  await expect(page.getByRole('alert')).toContainText('로그인이 필요')
  expect(state.current.profile.preferences.style).toBe('default')
  await page.getByRole('link', { name: '다시 로그인' }).click()
  await expect(page.getByRole('button', { name: '로그인하기' })).toBeVisible()
  await expect(page.getByLabel('비밀번호', { exact: true })).toHaveValue('')
})

test('설정을 취소하면 추천 조건을 변경하지 않는다', async ({ page }) => {
  const state = await mockAccount(page, { signedIn: true, profileReady: true })
  await page.goto('./#profile')
  await page.getByRole('radio', { name: '더위를 타요' }).check()
  await page.getByRole('button', { name: '추천으로 돌아가기' }).click()
  await expect(page.getByRole('heading', { name: /오늘, 뭐 입지/ })).toBeVisible()
  expect(state.calls.filter((call) => call.method === 'PUT')).toHaveLength(0)
  expect(state.current.profile.preferences.cold_sensitivity).toBe('normal')
})
