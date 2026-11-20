import type { Look } from './types'

const colors = [
  [/검정|검은|블랙|\bblack\b/, '#303436', '#f5f4ee'],
  [/흰색|흰|하얀|화이트|\bwhite\b/, '#fcfaf3', '#35423b'],
  [/네이비|남색|\bnavy\b/, '#2e4265', '#f5f4ee'],
  [/베이지|\bbeige\b/, '#c9b58e', '#35423b'],
  [/아이보리|크림색|\bivory\b|\bcream\b/, '#efe5cd', '#35423b'],
  [/차콜|\bcharcoal\b/, '#505458', '#f5f4ee'],
  [/그레이|회색|\bgr[ae]y\b/, '#93999a', '#35423b'],
  [/올리브|카키|\bolive\b|\bkhaki\b/, '#78845d', '#f5f4ee'],
  [/하늘색|연청|라이트\s*블루|\bsky blue\b|\blight blue\b/, '#a5c3d3', '#35423b'],
  [/파랑|파란|청색|블루|진청|\bblue\b/, '#557fa6', '#f5f4ee'],
  [/초록|녹색|그린|\bgreen\b/, '#638b71', '#f5f4ee'],
  [/버건디|와인색|\bburgundy\b/, '#834754', '#f5f4ee'],
  [/빨강|빨간|붉은|레드|\bred\b/, '#b85a50', '#f5f4ee'],
  [/분홍|핑크|\bpink\b/, '#ce929c', '#35423b'],
  [/갈색|브라운|\bbrown\b/, '#8b6c54', '#f5f4ee'],
  [/노랑|노란|옐로우|\byellow\b/, '#daba63', '#35423b'],
] as const

const shapes = {
  top: [
    [/민소매|나시|슬리브리스|\bsleeveless\b/, 'sleeveless'],
    [/긴팔|긴소매|\blong[ -]sleeve\b/, 'long-sleeve'],
    [/반팔|반소매|짧은\s*소매|\bshort[ -]sleeve\b|\bt[ -]shirt\b|티셔츠/, 'short-sleeve'],
    [/셔츠|니트|스웨터|맨투맨|후디|후드티/, 'long-sleeve'],
  ],
  outerwear: [[/코트|트렌치|\bcoat\b/, 'coat']],
  bottom: [
    [/치마|스커트|\bskirt\b/, 'skirt'],
    [/반바지|쇼츠|\bshorts\b|\bhalf[ -]pants\b/, 'shorts'],
  ],
  one_piece: [[/점프\s*수트|오버롤|\bjumpsuit\b|\boveralls\b/, 'jumpsuit']],
} as const

const defaultShape = {
  top: 'top',
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
  let fill = '#b4b2a5'
  let ink = '#35423b'
  let firstColorIndex = Infinity
  for (const [expression, colorFill, colorInk] of colors) {
    const match = expression.exec(text)
    if (match && match.index < firstColorIndex) {
      firstColorIndex = match.index
      fill = colorFill
      ink = colorInk
    }
  }
  const pattern = /줄무늬|스트라이프|단가라|\bstrip(?:ed|es?)\b/.test(text)
    ? 'stripes'
    : /체크|격자|깅엄|타탄|\b(?:check(?:ed|s)?|plaid|gingham)\b/.test(text)
      ? 'check'
      : null
  const shape =
    shapes[slot].find(([expression]) => expression.test(text))?.[1] ?? defaultShape[slot]
  return { slot, shape, fill, ink, pattern }
}

export function illustratedGarments(look: Look) {
  const slots: GarmentSlot[] =
    look.outfit_type === 'one_piece' ? ['one_piece', 'outerwear'] : ['top', 'outerwear', 'bottom']
  return slots.flatMap((slot) => {
    const name = look[slot]?.trim()
    return name ? [describeGarment(slot, name)] : []
  })
}
