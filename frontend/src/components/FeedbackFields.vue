<script setup lang="ts">
import { feedbackIssues } from '../types'
import type { FeedbackEdit, Look } from '../types'
const draft = defineModel<FeedbackEdit>({ required: true })
const lines = (event: Event) =>
  (event.target as HTMLTextAreaElement).value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
function changeType(look: Look) {
  if (look.outfit_type === 'one_piece') {
    look.top = null
    look.bottom = null
    look.one_piece = ''
  } else {
    look.one_piece = null
    look.top = ''
    look.bottom = ''
  }
}
</script>

<template>
  <fieldset class="feedback-issues">
    <legend>문제 유형</legend>
    <label v-for="[code, label] in feedbackIssues" :key="code">
      <input v-model="draft.issues" type="checkbox" :value="code" />{{ label }}
    </label>
  </fieldset>
  <label class="feedback-field"
    >문제 설명<textarea v-model="draft.note" rows="3" maxlength="2000" />
  </label>
  <template v-if="draft.corrected_day">
    <p>추천 조합과 의도적으로 피해야 할 조합을 구분해 수정해 주세요.</p>
    <fieldset
      v-for="[key, title] in [
        ['best', '추천 조합'],
        ['worst', '피해야 할 조합'],
      ] as const"
      :key="key"
      class="feedback-look"
    >
      <legend>{{ title }}</legend>
      <label class="feedback-field"
        >{{ title }} 구성
        <select
          v-model="draft.corrected_day[key].outfit_type"
          :aria-label="`${title} 구성`"
          @change="changeType(draft.corrected_day[key])"
        >
          <option value="separates">상의·하의</option>
          <option value="one_piece">원피스·점프수트</option>
        </select>
      </label>
      <template v-if="draft.corrected_day[key].outfit_type === 'separates'">
        <label class="feedback-field"
          >{{ title }} 상의<input v-model="draft.corrected_day[key].top" required maxlength="200"
        /></label>
        <label class="feedback-field"
          >{{ title }} 하의<input
            v-model="draft.corrected_day[key].bottom"
            required
            maxlength="200"
        /></label>
      </template>
      <label v-else class="feedback-field"
        >{{ title }} 원피스<input
          v-model="draft.corrected_day[key].one_piece"
          required
          maxlength="200"
      /></label>
      <label class="feedback-field"
        >{{ title }} 겉옷 (없으면 비움)<input
          :value="draft.corrected_day[key].outerwear ?? ''"
          maxlength="200"
          @input="
            draft.corrected_day[key].outerwear =
              ($event.target as HTMLInputElement).value.trim() || null
          "
      /></label>
      <label class="feedback-field"
        >{{ title }} 신발<input v-model="draft.corrected_day[key].shoes" required maxlength="200"
      /></label>
      <label class="feedback-field"
        >{{ title }} 준비물 (한 줄에 하나)<textarea
          :value="draft.corrected_day[key].accessories.join('\n')"
          rows="3"
          maxlength="2000"
          @change="draft.corrected_day[key].accessories = lines($event)"
        />
      </label>
    </fieldset>
    <label
      v-for="[key, title] in [
        ['reasons', '추천 이유'],
        ['avoid_reasons', '피해야 할 이유'],
        ['precautions', '주의 사항'],
      ] as const"
      :key="key"
      class="feedback-field"
    >
      {{ title }} (한 줄에 하나)<textarea
        :value="draft.corrected_day[key].join('\n')"
        rows="4"
        maxlength="8000"
        @change="draft.corrected_day[key] = lines($event)"
      />
    </label>
  </template>
</template>
