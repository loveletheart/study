<script setup lang="ts">
import { computed, useId } from 'vue'
import type { Look } from '../types'

const props = defineProps<{ look: Look }>()
const illustrationId = useId()

const colors = [
  { name: /검정|검은색|검은|블랙|\bblack\b/iu, fill: '#2c2b29', dark: true },
  { name: /흰색|흰|하얀|화이트|\bwhite\b/iu, fill: '#faf8f1' },
  { name: /네이비|남색|\bnavy\b/iu, fill: '#303f5d', dark: true },
  { name: /베이지|\bbeige\b/iu, fill: '#ddc7a0' },
  { name: /아이보리|크림색|\bivory\b/iu, fill: '#eee5cc' },
  { name: /회색|차콜|그레이|\bgr[ae]y\b/iu, fill: '#777a7d', dark: true },
  { name: /연청|하늘색|스카이\s?블루|\blight[ -]blue\b/iu, fill: '#a0bfcc' },
  { name: /진청|파랑|파란|청색|블루|\bblue\b/iu, fill: '#526f96', dark: true },
  { name: /올리브|카키|초록|녹색|그린|\b(?:olive|khaki|green)\b/iu, fill: '#758762' },
  { name: /갈색|브라운|\bbrown\b/iu, fill: '#8d604b', dark: true },
  { name: /분홍|핑크|\bpink\b/iu, fill: '#d6a1a9' },
  { name: /빨강|빨간|붉은|레드|\bred\b/iu, fill: '#a85953', dark: true },
]

const colorNames = colors.map(({ name }) => name.source).join('|')
const baseColorPattern = new RegExp(
  `(${colorNames})\\s*(?:바탕|배경|\\b(?:base|background)\\b)|` +
    `(?:바탕색|배경색|\\b(?:base|background) colou?r\\b)(?:은|이)?\\s*:?\\s*(${colorNames})`,
  'iu',
)

const patterns = [
  { name: /줄\s?무늬|스트라이프|\bstrip(?:e|ed|es)\b/iu, type: 'stripe' },
  { name: /체크|격자|\bcheck(?:ed|ered|s)?\b/iu, type: 'check' },
]

const dressDetail = 'M37 31Q55 49 73 31M37 103h36M43 111l-9 80m33-80 9 80'
const silhouettes = {
  sleeveless: {
    outline: 'M33 30h10Q55 56 67 30h10l4 14q-5 19 8 28l-6 73H27l-6-73q13-9 8-28Z',
    detail: 'M40 31Q55 59 70 31M28 137h54',
  },
  shortSleeve: {
    outline: 'M33 30 17 36 2 69l20 10 8-15-3 81h56l-3-81 8 15 20-10-15-33-16-6Q55 57 33 30Z',
    detail: 'M37 31Q55 49 73 31M28 137h54',
  },
  longSleeve: {
    outline: 'M33 30 17 36 3 133l20 4 9-65-5 73h56l-5-73 9 65 20-4-14-97-16-6Q55 57 33 30Z',
    detail: 'M37 31Q55 49 73 31M5 125l19 4m62 0 19-4M28 137h54',
  },
  jacket: {
    outline: 'M33 27 15 37 3 147l21 3 9-70-6 83h56l-6-83 9 70 21-3-12-110-18-10-22 9Z',
    detail: 'M33 27l-5 23 17 8-8 8 18 26 18-26-8-8 17-8-5-23M55 36v127M32 123h16m14 0h16',
  },
  pants: {
    outline: 'M25 31h60l7 167H60l-5-100-5 100H18Z',
    detail: 'M25 43h60M55 43v43M25 44l11 19m49-19L74 63m-55 127h31m10 0h31',
  },
  shorts: {
    outline: 'M25 31h60l9 91H62l-7-28-7 28H16Z',
    detail: 'M24 43h62M55 43v38M24 44l11 18m51-18L75 62M17 114h33m10 0h33',
  },
  skirt: {
    outline: 'M33 31h44l28 119q-50 13-100 0Z',
    detail: 'M30 44h50m-40 3-9 104m24-104v108m15-108 9 104',
  },
  dress: {
    outline:
      'M33 30 18 37 4 70l20 10 8-14 5 37-29 91q47 12 94 0l-29-91 5-37 8 14 20-10-14-33-15-7Q55 57 33 30Z',
    detail: dressDetail,
  },
  longSleeveDress: {
    outline:
      'M33 30 18 37 4 127l19 4 9-65 5 37-29 91q47 12 94 0l-29-91 5-37 9 65 19-4-14-90-15-7Q55 57 33 30Z',
    detail: dressDetail,
  },
  jumpsuit: {
    outline:
      'M33 30 17 36 2 69l20 10 8-15-3 37-9 97h32l5-70 5 70h32l-9-97-3-37 8 15 20-10-15-33-16-6Q55 57 33 30Z',
    detail: 'M37 31Q55 49 73 31M55 45v56M27 101h56m-64 89h31m10 0h31',
  },
}

type Shape = keyof typeof silhouettes
type GarmentSlot = 'top' | 'bottom' | 'outerwear' | 'one_piece'

function garmentShape(slot: GarmentSlot, label: string): Shape {
  switch (slot) {
    case 'outerwear':
      return 'jacket'
    case 'one_piece':
      if (/점프\s?[수슈]트|\bjumpsuit\b/iu.test(label)) return 'jumpsuit'
      return /긴팔|긴\s?소매|\blong[ -]sleeve/iu.test(label) ? 'longSleeveDress' : 'dress'
    case 'top':
      if (/민소매|\b(?:sleeveless|tank[ -]top)\b/iu.test(label)) return 'sleeveless'
      return /반팔|짧은\s?소매|\bshort[ -]sleeve/iu.test(label) ? 'shortSleeve' : 'longSleeve'
    case 'bottom':
      if (/스커트|치마|\bskirts?\b/iu.test(label)) return 'skirt'
      return /반바지|쇼츠|짧은\s?(?:바지|팬츠)|\bshorts\b/iu.test(label) ? 'shorts' : 'pants'
  }
}

const garments = computed(() => {
  const look = props.look
  const slots: GarmentSlot[] =
    look.outfit_type === 'one_piece' ? ['outerwear', 'one_piece'] : ['outerwear', 'top', 'bottom']

  return slots.flatMap((slot) => {
    const label = look[slot]?.trim()
    if (!label) return []

    const baseColor = baseColorPattern.exec(label)
    const colorLabel = baseColor?.[1] ?? baseColor?.[2] ?? label
    const color = colors.find(({ name }) => name.test(colorLabel))
    const pattern = patterns.find(({ name }) => name.test(label))
    const shape = garmentShape(slot, label)
    return [
      {
        slot,
        shape,
        ...silhouettes[shape],
        fill: color?.fill ?? '#bcb6a9',
        ink: color?.dark ? '#fffaf0' : '#453d32',
        patternId: `${illustrationId}-${slot}`,
        pattern: pattern?.type,
      },
    ]
  })
})
</script>

<template>
  <svg viewBox="0 0 380 260" fill="none" aria-hidden="true" class="wardrobe-art">
    <ellipse cx="190" cy="234" :rx="garments.length * 51" ry="8" fill="#545143" opacity=".08" />
    <g
      v-for="(garment, index) in garments"
      :key="garment.slot"
      :data-garment="garment.slot"
      :data-shape="garment.shape"
      :transform="`translate(${190 - (garments.length * 118) / 2 + index * 118 + 4}, 20)`"
    >
      <defs v-if="garment.pattern">
        <pattern
          :id="garment.patternId"
          :data-pattern="garment.pattern"
          patternUnits="userSpaceOnUse"
          width="15"
          height="15"
        >
          <path d="M0 6h15" :stroke="garment.ink" stroke-width="4" opacity=".45" />
          <path
            v-if="garment.pattern === 'check'"
            d="M6 0v15"
            :stroke="garment.ink"
            stroke-width="4"
            opacity=".45"
          />
        </pattern>
      </defs>
      <path
        :d="garment.outline"
        :fill="garment.fill"
        stroke="#65584c"
        stroke-opacity=".55"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
      <path v-if="garment.pattern" :d="garment.outline" :fill="`url(#${garment.patternId})`" />
      <path :d="garment.detail" :stroke="garment.ink" opacity=".45" stroke-width="2" />
    </g>
  </svg>
</template>
