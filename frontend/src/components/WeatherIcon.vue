<script setup lang="ts">
import { computed } from 'vue'
const props = withDefaults(defineProps<{ code?: number; night?: boolean; size?: number }>(), {
  code: 0,
  size: 48,
})
const kind = computed(() =>
  props.code >= 95
    ? 'storm'
    : (props.code >= 71 && props.code <= 77) || props.code === 85 || props.code === 86
      ? 'snow'
      : props.code >= 51
        ? 'rain'
        : props.code >= 45
          ? 'fog'
          : props.code >= 2
            ? 'cloud'
            : props.night
              ? 'night'
              : 'sun',
)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 80 80"
    fill="none"
    aria-hidden="true"
    class="weather-icon"
  >
    <g v-if="kind === 'sun' || code === 2">
      <g stroke="#d5a854" stroke-width="3" stroke-linecap="round">
        <path d="M40 6v6m0 56v6M6 40h6m56 0h6M16 16l5 5m38 38 5 5M16 64l5-5m38-38 5-5" />
      </g>
      <circle cx="40" cy="40" r="18" fill="#efcc7e" />
      <circle cx="40" cy="40" r="12" fill="#f4d994" />
    </g>
    <path
      v-else-if="kind === 'night'"
      d="M54 15a26 26 0 1 0 10 42A29 29 0 0 1 54 15Z"
      fill="#ddca89"
    />
    <g v-if="!['sun', 'night'].includes(kind)">
      <path d="M20 55a13 13 0 0 1-1-26 21 21 0 0 1 39-2 14 14 0 1 1 4 28H20Z" fill="#c3d3d1" />
      <path
        d="M20 55a13 13 0 0 1-1-26 21 21 0 0 1 12-13"
        stroke="#dce5e1"
        stroke-width="3"
        stroke-linecap="round"
      />
      <path
        v-if="kind === 'rain'"
        d="m25 63-4 8m20-8-4 8m20-8-4 8"
        stroke="#789cbb"
        stroke-width="3"
        stroke-linecap="round"
      />
      <path
        v-if="kind === 'snow'"
        d="M24 63v10m-4-7 8 4m0-4-8 4m27-7v10m-4-7 8 4m0-4-8 4"
        stroke="#789cbb"
        stroke-width="2"
        stroke-linecap="round"
      />
      <path
        v-if="kind === 'fog'"
        d="M14 64h52M20 71h38"
        stroke="#a2b9ae"
        stroke-width="3"
        stroke-linecap="round"
      />
      <path v-if="kind === 'storm'" d="m43 48-12 17h11l-4 12 17-21H44l5-8" fill="#e2b460" />
    </g>
  </svg>
</template>
