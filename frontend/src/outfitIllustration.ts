import type { Look } from './types'

const colors = [
  [/검정|검은|블랙|\bblack\b/, '#2c2b29', '#fffaf0'],
  [/흰색|흰|하얀|화이트|\bwhite\b/, '#faf8f1', '#453d32'],
  [/네이비|남색|\bnavy\b/, '#303f5d', '#fffaf0'],
  [/베이지|\bbeige\b/, '#ddc7a0', '#453d32'],
  [/아이보리|크림색|\bivory\b|\bcream\b/, '#eee5cc', '#453d32'],
  [/차콜|\bcharcoal\b/, '#505458', '#fffaf0'],
  [/그레이|회색|\bgr[ae]y\b/, '#777a7d', '#fffaf0'],
  [/올리브|카키|\bolive\b|\bkhaki\b/, '#758762', '#453d32'],
  [/하늘색|연청|(?:라이트|스카이)\s*블루|\b(?:sky|light)[ -]blue\b/, '#a0bfcc', '#453d32'],
  [/파랑|파란|청색|블루(?!종)|진청|\bblue\b/, '#526f96', '#fffaf0'],
  [/초록|녹색|그린|\bgreen\b/, '#758762', '#453d32'],
  [/버건디|와인색|\bburgundy\b/, '#834754', '#fffaf0'],
  [/빨강|빨간|붉은|레드|\bred\b/, '#a85953', '#fffaf0'],
  [/분홍|핑크|\bpink\b/, '#d6a1a9', '#453d32'],
  [/갈색|브라운|\bbrown\b/, '#8d604b', '#fffaf0'],
  [/노랑|노란|옐로우|\byellow\b/, '#daba63', '#453d32'],
] as const

const colorNames = colors.map(([expression]) => expression.source).join('|')
const baseColorPattern = new RegExp(
  `(${colorNames})\\s*(?:바탕|배경|\\b(?:base|background)\\b)|` +
    `(?:바탕색|배경색|\\b(?:base|background) colou?r\\b)(?:은|이)?\\s*:?\\s*(${colorNames})`,
  'u',
)

const shapes = {
  top: [
    [/민소매|나시|슬리브리스|\b(?:sleeveless|tank[ -]top)\b/, 'sleeveless'],
    [/긴팔|긴\s*소매|\blong[ -]sleeve/, 'longSleeve'],
    [/반팔|반소매|짧은\s*소매|\bshort[ -]sleeve|\bt[ -]shirt\b|티셔츠/, 'shortSleeve'],
  ],
  outerwear: [[/코트|트렌치|\bcoat\b/, 'coat']],
  bottom: [
    [/치마|스커트|\bskirts?\b/, 'skirt'],
    [/반바지|쇼츠|짧은\s*(?:바지|팬츠)|\bshorts\b|\bhalf[ -]pants\b/, 'shorts'],
  ],
  one_piece: [
    [/점프\s*[수슈]트|오버롤|\bjumpsuit\b|\boveralls\b/, 'jumpsuit'],
    [/긴팔|긴\s*소매|\blong[ -]sleeve/, 'longSleeveDress'],
  ],
} as const

const defaultShape = {
  top: 'longSleeve',
  outerwear: 'jacket',
  bottom: 'pants',
  one_piece: 'dress',
} as const

export type GarmentSlot = keyof typeof defaultShape
export type GarmentShape =
  | (typeof defaultShape)[GarmentSlot]
  | (typeof shapes)[GarmentSlot][number][1]

function describeGarment(slot: GarmentSlot, name: string) {
  const text = name.normalize('NFKC').toLowerCase()
  const background = baseColorPattern.exec(text)
  const colorLabel = background?.[1] ?? background?.[2] ?? text
  let fill = '#bcb6a9'
  let ink = '#453d32'
  let firstColorIndex = Infinity
  for (const [expression, colorFill, colorInk] of colors) {
    const match = expression.exec(colorLabel)
    if (match && match.index < firstColorIndex) {
      firstColorIndex = match.index
      fill = colorFill
      ink = colorInk
    }
  }
  const pattern = /줄\s*무늬|스트라이프|단가라|\bstrip(?:e|ed|es)\b/.test(text)
    ? 'stripe'
    : /체크|격자|깅엄|타탄|\b(?:check(?:ed|ered|s)?|plaid|gingham)\b/.test(text)
      ? 'check'
      : null
  const shape =
    shapes[slot].find(([expression]) => expression.test(text))?.[1] ?? defaultShape[slot]
  return { slot, shape, fill, ink, pattern }
}

export function illustratedGarments(look: Look) {
  const slots: GarmentSlot[] =
    look.outfit_type === 'one_piece' ? ['outerwear', 'one_piece'] : ['outerwear', 'top', 'bottom']
  return slots.flatMap((slot) => {
    const name = look[slot]?.trim()
    return name ? [describeGarment(slot, name)] : []
  })
}
