<script setup lang="ts">
import { computed, useId } from 'vue'
import type { Look } from '../types'
import { illustratedGarments, type GarmentShape } from '../outfitIllustration'

const props = defineProps<{ look: Look }>()
const patternId = useId()
const garments = computed(() => illustratedGarments(props.look))

// 추천에 포함된 의류 수에 맞춰 각 형태를 겹치지 않게 배치한다.
const positions = [
  [],
  ['translate(55 34) scale(1.5)'],
  ['translate(16 35) scale(1.12)', 'translate(133 72) scale(1.12)'],
  ['translate(23 13)', 'translate(137 13)', 'translate(80 114)'],
]
const layout = computed(() => positions[garments.value.length] ?? [])

const shapes: Record<GarmentShape, { outline: string; seams: string }> = {
  top: {
    outline: 'M35 13 20 20 5 44l17 10 9-13v49q19 5 38 0V41l9 13 17-10-15-24-15-7q-15 17-30 0Z',
    seams: 'M36 14q14 21 28 0M31 85q19 5 38 0',
  },
  'short-sleeve': {
    outline: 'M35 13 18 20 5 36l16 14 10-11v51q19 5 38 0V39l10 11 16-14-13-16-17-7q-15 16-30 0Z',
    seams: 'M36 14q14 21 28 0M9 32l16 13m50 0 16-13M31 85q19 5 38 0',
  },
  'long-sleeve': {
    outline: 'M35 13 17 20 4 65l16 6 11-28v47q19 5 38 0V43l11 28 16-6-13-45-18-7q-15 16-30 0Z',
    seams: 'M36 14q14 21 28 0M6 59l16 6m56 0 16-6M31 85q19 5 38 0',
  },
  sleeveless: {
    outline: 'M31 13h11q1 19 8 19t8-19h11q-1 21 8 27l-6 51q-21 4-42 0l-6-51q9-6 8-27Z',
    seams: 'M40 14q2 22 10 22t10-22M29 86q21 4 42 0',
  },
  jacket: {
    outline: 'M35 14 18 22 4 71l17 5 10-31-3 46q22 4 44 0l-3-46 10 31 17-5-14-49-17-8-15 8Z',
    seams: 'M35 14l5 22 10-14 10 14 5-22M50 22v71M35 63h8m14 0h8M6 66l16 5m56 0 16-5',
  },
  coat: {
    outline: 'M35 11 19 19 5 63l16 6 10-29-8 55 27 3 27-3-8-55 10 29 16-6-14-44-16-8-15 9Z',
    seams: 'M35 11l4 23 11-14 11 14 4-23M50 20v77M32 63l10-6m16 0 10 6M25 90l25 4 25-4',
  },
  pants: {
    outline: 'M24 9h52l6 85H56l-6-53-6 53H18l6-85Z',
    seams: 'M24 17h52M50 17v24M25 28l9-10m32 0 9 10M19 89h25m12 0h25',
  },
  shorts: {
    outline: 'M24 22h52l9 49H55l-5-20-5 20H15l9-49Z',
    seams: 'M23 30h54M50 30v21M22 40l12-10m32 0 12 10M16 65h30m8 0h30',
  },
  skirt: {
    outline: 'M29 19h42l13 63q-34 10-68 0l13-63Z',
    seams: 'M27 27h46M39 30l-6 52m17-52v54m11-54 6 52',
  },
  dress: {
    outline:
      'M34 10 21 15 9 34l16 11 9-10-2 13-13 44q31 11 62 0L68 48l-2-13 9 10 16-11-12-19-13-5q-16 17-32 0Z',
    seams: 'M36 12q14 23 28 0M32 48q18 5 36 0M39 53l-6 36m28-36 6 36',
  },
  jumpsuit: {
    outline: 'M33 10h10v18h14V10h10l8 30 7 55H56l-6-33-6 33H18l7-55 8-30Z',
    seams: 'M26 44h48M40 31h20v10H40ZM50 44v18M19 90h25m12 0h25',
  },
}
</script>

<template>
  <svg class="outfit-illustration" viewBox="0 0 260 220" fill="none" aria-hidden="true">
    <g
      v-for="(garment, index) in garments"
      :key="garment.slot"
      :transform="layout[index]"
      :data-garment="garment.slot"
      :data-shape="garment.shape"
      :data-pattern="garment.pattern"
    >
      <defs v-if="garment.pattern">
        <pattern
          :id="`${patternId}-${garment.slot}`"
          width="10"
          height="10"
          patternUnits="userSpaceOnUse"
        >
          <path
            :d="garment.pattern === 'check' ? 'M0 3h10M3 0v10' : 'M0 3h10'"
            :stroke="garment.ink"
            stroke-width="2.5"
            opacity=".57"
          />
        </pattern>
      </defs>
      <path class="garment-fill" :d="shapes[garment.shape].outline" :fill="garment.fill" />
      <path
        :d="shapes[garment.shape].outline"
        :fill="garment.pattern ? `url(#${patternId}-${garment.slot})` : 'none'"
        stroke="#323d36"
        stroke-opacity=".46"
        stroke-width="1.4"
        stroke-linejoin="round"
      />
      <path
        :d="shapes[garment.shape].seams"
        :stroke="garment.ink"
        stroke-opacity=".62"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </g>
  </svg>
</template>
