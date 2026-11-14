<script setup lang="ts">
import { computed } from 'vue'
import type { Look } from '../types'
import AppIcon from './AppIcon.vue'
import WardrobeArt from './WardrobeArt.vue'

const props = defineProps<{
  look: Look
  reasons: string[]
  avoid?: boolean
  comparisonLook?: Look
}>()
const title = computed(() => (props.avoid ? '워스트 옷차림' : '베스트 옷차림'))
const reasonPreviewLength = 100
const explanation = computed(() => {
  const [first, ...remaining] = props.reasons
  if (
    !first ||
    !props.comparisonLook ||
    Array.from(props.reasons.join(' ')).length <= reasonPreviewLength
  ) {
    return { preview: props.reasons, details: [] }
  }

  const characters = Array.from(first)
  if (characters.length <= reasonPreviewLength) {
    return { preview: [first], details: remaining }
  }

  const excerpt = characters.slice(0, reasonPreviewLength).join('').trimEnd()
  return { preview: [`${excerpt}…`], details: props.reasons }
})

const clothingFields = [
  ['outerwear', '겉옷'],
  ['top', '상의'],
  ['bottom', '하의'],
  ['one_piece', '원피스'],
  ['shoes', '신발'],
] as const
const clothes = computed(() =>
  clothingFields.filter(([field]) => props.look[field] || props.comparisonLook?.[field]),
)
</script>

<template>
  <article class="outfit-card" :class="{ 'avoid-card': avoid }">
    <h3 class="outfit-card-heading">
      <AppIcon :name="avoid ? 'info' : 'check'" :size="17" />{{ title }}
    </h3>
    <div class="outfit-card-body">
      <div class="look-art">
        <WardrobeArt
          :variant="avoid ? 'worst' : 'best'"
          :one-piece="look.outfit_type === 'one_piece'"
        /><span>옷차림 예시 일러스트</span>
      </div>
      <dl class="clothing-list">
        <div v-for="[field, label] in clothes" :key="field">
          <dt>{{ label }}</dt>
          <dd>{{ look[field] ?? '없음' }}</dd>
        </div>
        <div v-if="look.accessories.length || comparisonLook?.accessories.length">
          <dt>준비물</dt>
          <dd>{{ look.accessories.join(' · ') || '없음' }}</dd>
        </div>
      </dl>
    </div>
    <div v-if="reasons.length" class="outfit-reasons">
      <span class="reason-label">{{ avoid ? '피하면 좋은 이유' : '이 조합을 고른 이유' }}</span>
      <p v-for="(reason, index) in explanation.preview" :key="index">{{ reason }}</p>
      <details v-if="explanation.details.length" class="outfit-reason-details">
        <summary :aria-label="`${title} 이유 자세히 보기`">이유 자세히 보기</summary>
        <p v-for="(reason, index) in explanation.details" :key="index">{{ reason }}</p>
      </details>
    </div>
  </article>
</template>
