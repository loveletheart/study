import { test, expect } from '@playwright/test'
import { mockApi, success, failure, location } from './fixtures.js'

test('포함 검색의 전체 건수와 다음 페이지를 표시하고 기존 결과를 유지한다', async ({ page }) => {
  await mockApi(page)
  const calls = []
  const rows = Array.from({ length: 23 }, (_, i) => ({ ...location, id: 200000 + i, name: i === 0 ? '남서울동' : `서울 ${i}동` }))
  let failOnce = true
  await page.route('**/weather/locations?**', route => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset'))
    calls.push({ query: url.searchParams.get('query'), offset })
    if (offset === 20 && failOnce) {
      failOnce = false
      return route.fulfill({ status: 503, json: failure('WEATHER_UNAVAILABLE', '다음 결과를 불러오지 못했어요.') })
    }
    return route.fulfill({ json: success({ locations: rows.slice(offset, offset + 20), total: rows.length, offset, limit: 20, has_more: offset + 20 < rows.length, attribution: 'GeoNames' }) })
  })
  await page.goto('./')
  await page.getByRole('button', { name: '내 지역 선택' }).click()
  await page.getByRole('searchbox', { name: '지역명' }).fill('서울')
  await expect(page.locator('.search-result-count')).toContainText('23개 지역 중 20개 표시')
  await expect(page.locator('.region-result')).toHaveCount(20)
  await expect(page.locator('.region-result').first()).toContainText('남서울동')
  await page.getByRole('button', { name: '관련 지역 더 보기' }).click()
  await expect(page.getByRole('button', { name: '더 보기 다시 시도' })).toBeVisible()
  await expect(page.locator('.region-result')).toHaveCount(20)
  await page.getByRole('button', { name: '더 보기 다시 시도' }).click()
  await expect(page.locator('.region-result')).toHaveCount(23)
  await expect(page.locator('.search-result-count')).toContainText('23개 지역 중 23개 표시')
  await expect(page.getByRole('button', { name: '관련 지역 더 보기' })).not.toBeVisible()
  expect(calls).toEqual([{ query: '서울', offset: 0 }, { query: '서울', offset: 20 }, { query: '서울', offset: 20 }])
})

test('검색어를 바꾸면 페이지를 초기화하고 이전의 늦은 결과를 섞지 않는다', async ({ page }) => {
  await mockApi(page)
  let release
  const delayed = new Promise(resolve => { release = resolve })
  await page.route('**/weather/locations?**', async route => {
    const url = new URL(route.request().url())
    const offset = Number(url.searchParams.get('offset'))
    const query = url.searchParams.get('query')
    if (query === '서울' && offset > 0) await delayed
    const locations = [{ ...location, id: query === '서울' ? offset + 1 : 999, name: query === '서울' ? '서울 후보' : '강남구' }]
    await route.fulfill({ json: success({ locations, total: query === '서울' ? 2 : 1, offset, limit: 20, has_more: query === '서울' && offset === 0, attribution: 'GeoNames' }) }).catch(() => {})
  })
  await page.goto('./')
  await page.getByRole('button', { name: '내 지역 선택' }).click()
  await page.getByRole('searchbox', { name: '지역명' }).fill('서울')
  await page.getByRole('button', { name: '관련 지역 더 보기' }).click()
  await page.getByRole('searchbox', { name: '지역명' }).fill('서울 강남')
  await expect(page.locator('.region-result')).toContainText('강남구')
  release()
  await expect(page.locator('.region-result')).toHaveCount(1)
  await expect(page.locator('.region-result')).not.toContainText('서울 후보')
  await expect(page.locator('.search-result-count')).toContainText('1개 지역 중 1개 표시')
})
