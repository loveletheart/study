<script setup lang="ts">
withDefaults(defineProps<{ variant?: 'hero' | 'best' | 'worst'; onePiece?: boolean }>(), {
  variant: 'hero',
  onePiece: false,
})
</script>

<template>
  <svg viewBox="0 0 380 300" fill="none" aria-hidden="true" class="wardrobe-art">
    <ellipse cx="190" cy="277" rx="137" ry="12" fill="currentColor" opacity=".06" />
    <circle v-if="variant === 'hero'" cx="207" cy="137" r="112" fill="#e5ebd6" />
    <g :transform="onePiece ? 'translate(65, 3)' : 'translate(12, 0)'">
      <path
        d="M122 21c-10-11 5-25 16-16 9 9-5 16-5 16v9m0 0-58 30h116l-58-30"
        stroke="#897d64"
        stroke-width="3"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <g v-if="!onePiece">
        <path
          d="m103 49-22 11-37 45 27 22 21-23-7 118c20 7 73 7 96 0l-8-118 21 23 27-22-37-45-22-11-29 14-30-14Z"
          :fill="variant === 'worst' ? '#c9b89c' : '#6c8467'"
        />
        <path
          d="m103 49 30 14-18 25-20-33m67-6-29 14 18 25 20-33"
          :fill="variant === 'worst' ? '#b2a083' : '#526d50'"
        />
        <path
          d="M133 65v161m-31-96-2 34h22m41-34 2 34h-22M88 215c30 6 59 6 91 0"
          stroke="currentColor"
          opacity=".25"
          stroke-width="2"
        />
        <g fill="#ded5b6">
          <circle cx="142" cy="103" r="2" />
          <circle cx="142" cy="134" r="2" />
          <circle cx="142" cy="166" r="2" />
          <circle cx="142" cy="197" r="2" />
        </g>
      </g>
      <g v-else>
        <path
          d="m106 50-17 13-24 39 26 17 17-28 2 44-30 115c36 10 72 10 108 0l-30-115 2-44 17 28 26-17-24-39-17-13c-12 16-41 16-56 0Z"
          :fill="variant === 'worst' ? '#bca98d' : '#738b72'"
        />
        <path
          d="M110 135h48m-40 7-14 101m30-99v104m16-106 14 101"
          stroke="currentColor"
          opacity=".22"
          stroke-width="2"
        />
        <path d="M109 55c8 29 40 29 50 0" stroke="#b2c4a4" stroke-width="3" />
      </g>
    </g>
    <g v-if="!onePiece" transform="translate(215, 132) rotate(7)">
      <path
        d="M8 0h85l-5 119H53l-4-72-7 72H8L8 0Z"
        :fill="variant === 'worst' ? '#7e837d' : '#e2d4b7'"
      />
      <path
        d="M9 13h82M49 15v31M17 117h23m16 0h30"
        stroke="#6c6c55"
        opacity=".3"
        stroke-width="2"
      />
      <path d="m22 14-2 14m59-14 1 14" stroke="#6c6c55" opacity=".2" stroke-width="2" />
    </g>
    <g v-if="variant === 'hero'" transform="translate(260, 50)">
      <path d="m0 19 25-19 25 19v37H0V19Z" fill="#e9dfb6" />
      <path d="M15 14V6a10 10 0 0 1 20 0v8" stroke="#af9c6f" stroke-width="3" />
      <path d="M4 50h42" stroke="#c4b484" stroke-width="2" />
    </g>
    <g v-if="variant === 'hero'" fill="#8a9b74">
      <path d="m45 216 3 11 11 3-11 3-3 11-3-11-11-3 11-3 3-11Z" />
      <circle cx="316" cy="166" r="3" />
      <circle cx="76" cy="36" r="3" />
    </g>
  </svg>
</template>
