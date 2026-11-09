<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Preferences } from '../types'
import PreferenceFields from './PreferenceFields.vue'
import AppIcon from './AppIcon.vue'
const props = defineProps<{ value: Preferences; busy?: boolean; error?: string }>()
const emit = defineEmits<{ close: []; apply: [value: Preferences] }>()
const draft = ref<Preferences>({ ...props.value, avoid_items: [...props.value.avoid_items] })
const dialog = ref<HTMLDialogElement>()
onMounted(() => dialog.value?.showModal())
</script>

<template>
  <dialog
    ref="dialog"
    class="modal preference-modal"
    aria-labelledby="preference-title"
    @cancel.prevent="emit('close')"
    @click="
      (event) => {
        if (event.target === dialog) emit('close')
      }
    "
  >
    <div class="modal-heading">
      <div>
        <p class="eyebrow">A LITTLE MORE YOU</p>
        <h2 id="preference-title">나에게 더 맞는 옷차림</h2>
      </div>
      <button class="icon-button" aria-label="취향 설정 닫기" @click="emit('close')">
        <AppIcon name="close" />
      </button>
    </div>
    <p class="muted">나의 체감과 오늘의 계획을 추천에 더해 보세요.</p>
    <form @submit.prevent="emit('apply', { ...draft })">
      <fieldset class="form-fields" :disabled="busy"><PreferenceFields v-model="draft" /></fieldset>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <p class="modal-footnote">
        처음 선택한 취향은 준비 시간이 필요해요. 주간 추천에는 다음 새벽 준비 작업부터 반영돼요.
      </p>
      <button type="submit" class="primary-button full-width" :disabled="busy">
        {{ busy ? '저장하고 있어요' : '내 취향 반영하기' }}<AppIcon name="arrow" :size="18" />
      </button>
    </form>
  </dialog>
</template>
