<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  logout: 'M9 4H4v16h5m4-4 4-4-4-4m-5 4h13',
  sun: 'M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17m10-10 1.4-1.4M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  calendar:
    'M8 3v4m8-4v4M4 10h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1m3 9h2m4 0h2m-8 3h2m4 0h2',
  pin: 'M20 10c0 6-8 11-8 11S4 16 4 10a8 8 0 1 1 16 0ZM15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  search: 'm16.5 16.5 4 4M18 10.5a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  chevron: 'm9 5 7 7-7 7',
  close: 'm6 6 12 12M6 18 18 6',
  check: 'm5 12 4 4L19 6',
  sliders: 'M4 7h5m5 0h6M4 17h10m5 0h1M9 4v6m5 4v6',
  refresh: 'M20 7v5h-5M4 17v-5h5m10.5-4A8 8 0 0 0 5.3 5.5L4 7m16 10-1.3 1.5A8 8 0 0 1 4.5 16',
  wind: 'M3 8h11a3 3 0 1 0-3-3M2 12h17a3 3 0 1 1-3 3M4 16h5a3 3 0 1 1-3 3',
  drop: 'M12 3C9 7 5 11 5 15a7 7 0 0 0 14 0c0-4-4-8-7-12Z',
  thermometer: 'M9 14.5V5a3 3 0 0 1 6 0v9.5a5 5 0 1 1-6 0ZM12 8v10',
  hanger: 'M10 6a2 2 0 1 1 3 1.7L12 9v2m0 0L3 17a1 1 0 0 0 .6 2h16.8a1 1 0 0 0 .6-2l-9-6',
  shirt: 'm8 3 4 2 4-2 6 5-4 4-2-2v11H8V10l-2 2-4-4 6-5Z',
  leaf: 'M20 3C6 1 2 9 6 15s14 6 14-12ZM4 21 16 8',
  info: 'M12 11v6m0-10h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  clock: 'M12 6v6l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  sparkles: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Zm7-1v4m-2-2h4',
}
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="paths[name] || paths.sun" />
  </svg>
</template>
