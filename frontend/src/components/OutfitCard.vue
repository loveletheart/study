<script setup lang="ts">
import { computed } from 'vue'
import type { Look } from '../types'
import AppIcon from './AppIcon.vue'
import WardrobeArt from './WardrobeArt.vue'
const props = defineProps<{ look: Look; reasons: string[]; avoid?: boolean }>()
const clothes = computed(() => {
  const items: [string, string | null][] = [
    ['겉옷', props.look.outerwear],
    ['상의', props.look.top],
    ['하의', props.look.bottom],
    ['원피스', props.look.one_piece],
    ['신발', props.look.shoes],
  ]
  return items.filter((item): item is [string, string] => item[1] !== null)
})
</script>

<template>
  <article class="outfit-card" :class="{ 'avoid-card': avoid }">
    <div class="outfit-card-heading">
      <span class="look-tag"
        ><AppIcon :name="avoid ? 'info' : 'check'" :size="15" />{{
          avoid ? '이런 조합은 잠깐' : '오늘의 추천 조합'
        }}</span
      ><span class="micro">{{ avoid ? 'BETTER TO AVOID' : 'YOUR WEATHER FIT' }}</span>
    </div>
    <div class="outfit-card-body">
      <div class="look-art">
        <WardrobeArt
          :variant="avoid ? 'worst' : 'best'"
          :one-piece="look.outfit_type === 'one_piece'"
        /><span>옷차림 예시 일러스트</span>
      </div>
      <dl class="clothing-list">
        <div v-for="[label, value] in clothes" :key="label">
          <dt>{{ label }}</dt>
          <dd>{{ value }}</dd>
        </div>
        <div v-if="look.accessories.length">
          <dt>준비물</dt>
          <dd>{{ look.accessories.join(' · ') }}</dd>
        </div>
      </dl>
    </div>
    <div class="outfit-reasons">
      <span class="reason-label">{{ avoid ? '피하면 좋은 이유' : '이 조합을 고른 이유' }}</span>
      <p v-for="reason in reasons" :key="reason">{{ reason }}</p>
    </div>
  </article>
</template>
