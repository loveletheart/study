<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { createFeedback, feedbackError } from '../api'
import type { FeedbackEdit, GeneratedDay } from '../types'
import { validateFeedbackEdit } from '../types'
import FeedbackFields from './FeedbackFields.vue'
const props = defineProps<{ generationId: string; day: GeneratedDay }>()
const emit = defineEmits<{ close: []; saved: []; expired: [] }>()
const dialog = ref<HTMLDialogElement>()
const draft = ref<FeedbackEdit>({ issues: [], note: '', corrected_day: null })
const busy = ref(false)
const error = ref('')
const controller = new AbortController()
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => controller.abort())
function toggleCorrection(event: Event) {
  draft.value.corrected_day = (event.target as HTMLInputElement).checked
    ? JSON.parse(JSON.stringify(props.day))
    : null
}
async function submit() {
  if (busy.value) return
  error.value = validateFeedbackEdit(draft.value)
  if (error.value) return
  busy.value = true
  error.value = ''
  try {
    await createFeedback(
      { generation_id: props.generationId, date: props.day.date, ...draft.value },
      controller.signal,
    )
    if (!controller.signal.aborted) emit('saved')
  } catch (cause) {
    if (!controller.signal.aborted) {
      error.value = feedbackError(cause)
      if ((cause as { status?: number }).status === 401) emit('expired')
    }
  } finally {
    if (!controller.signal.aborted) busy.value = false
  }
}
</script>

<template>
  <dialog
    ref="dialog"
    class="modal feedback-dialog"
    aria-labelledby="feedback-title"
    @cancel.prevent="emit('close')"
  >
    <div class="feedback-actions">
      <h2 id="feedback-title">답변 문제 신고·수정</h2>
      <button type="button" class="secondary-button" @click="emit('close')">닫기</button>
    </div>
    <p>
      {{ day.date }}에 표시된 답변을 신고해요. 피해야 할 조합 자체가 잘못된 답변이라는 뜻은
      아니에요.
    </p>
    <form @submit.prevent="submit">
      <fieldset :disabled="busy" class="feedback-form">
        <label
          ><input type="checkbox" :checked="!!draft.corrected_day" @change="toggleCorrection" />직접
          수정안 작성</label
        >
        <FeedbackFields v-model="draft" />
      </fieldset>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <p>
        원본은 서버의 생성 기록으로 확인해요. 수정안 저장 후 내 수정안 검수에서 별도로 승인할 수
        있어요.
      </p>
      <button type="submit" class="primary-button" :disabled="busy">
        {{ busy ? '저장 중' : draft.corrected_day ? '수정안 초안 저장' : '문제 신고 저장' }}
      </button>
    </form>
  </dialog>
</template>
