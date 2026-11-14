<script setup lang="ts">
import type { Preferences } from '../types'
import { preferenceOptions, clothingOptions, avoidOptions } from '../utils'
import AppIcon from './AppIcon.vue'
const model = defineModel<Preferences>({ required: true })
</script>

<template>
  <fieldset v-for="group in preferenceOptions" :key="group.key" class="preference-group">
    <legend>{{ group.label }}</legend>
    <p>{{ group.description }}</p>
    <div class="option-row">
      <label
        v-for="[value, label] in group.options"
        :key="value"
        class="preference-option"
        :class="{ selected: model[group.key] === value }"
        ><input v-model="model[group.key]" type="radio" :name="group.key" :value="value" /><span>{{
          label
        }}</span
        ><AppIcon v-if="model[group.key] === value" name="check" :size="14"
      /></label>
    </div>
  </fieldset>
  <fieldset class="preference-group">
    <legend>선호하는 의류 유형 <span class="optional-label">선택</span></legend>
    <p>남성복이나 여성복을 선택하면 해당 스타일과 공용 의류를 추천해요.</p>
    <div class="option-row">
      <label
        v-for="[value, label] in clothingOptions"
        :key="value"
        class="preference-option"
        :class="{ selected: model.clothing_preference === value }"
        ><input
          v-model="model.clothing_preference"
          type="radio"
          name="clothing_preference"
          :value="value" /><span>{{ label }}</span
        ><AppIcon v-if="model.clothing_preference === value" name="check" :size="14"
      /></label>
    </div>
  </fieldset>
  <fieldset class="preference-group">
    <legend>피하고 싶은 옷 <span class="optional-label">선택 · 여러 개 가능</span></legend>
    <p>베스트 추천에서 제외하도록 요청할게요.</p>
    <div class="avoid-options">
      <label
        v-for="[value, label] in avoidOptions"
        :key="value"
        class="avoid-option"
        :class="{ selected: model.avoid_items.includes(value) }"
        ><input v-model="model.avoid_items" type="checkbox" :value="value" /><AppIcon
          v-if="model.avoid_items.includes(value)"
          name="check"
          :size="14"
        /><span>{{ label }}</span></label
      >
    </div>
  </fieldset>
</template>
