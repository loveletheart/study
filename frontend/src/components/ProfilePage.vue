<script setup lang="ts">
import { ref } from 'vue'
import type { Account, Location, Preferences, ProfileInput } from '../types'
import { locationLabel } from '../utils'
import AppIcon from './AppIcon.vue'
import PreferenceFields from './PreferenceFields.vue'
import RegionPicker from './RegionPicker.vue'
const props = defineProps<{ account: Account; busy: boolean; error: string }>()
const emit = defineEmits<{ save: [profile: ProfileInput]; close: [] }>()
const name = ref(props.account.user.name)
const location = ref<Location | null>(props.account.profile.location)
const preferences = ref<Preferences>({
  ...props.account.profile.preferences,
  avoid_items: [...props.account.profile.preferences.avoid_items],
})
const regionOpen = ref(false)
const locationError = ref('')
const regionButton = ref<HTMLButtonElement>()
function submit() {
  if (!location.value) {
    locationError.value = '추천받을 지역을 선택해 주세요.'
    regionButton.value?.focus()
    return
  }
  locationError.value = ''
  emit('save', {
    name: name.value.trim(),
    location_id: location.value.id,
    preferences: { ...preferences.value, avoid_items: [...preferences.value.avoid_items].sort() },
  })
}
function selectLocation(value: Location) {
  location.value = value
  locationError.value = ''
  regionOpen.value = false
  regionButton.value?.focus()
}
</script>

<template>
  <main class="profile-page">
    <header class="profile-header">
      <a class="account-brand" href="#main-content" @click.prevent="emit('close')"
        >온도<span>°</span></a
      ><button class="secondary-button" :disabled="busy" @click="emit('close')">
        {{ account.profile.location ? '추천으로 돌아가기' : '나중에 설정하기'
        }}<AppIcon name="arrow" :size="16" />
      </button>
    </header>
    <div class="profile-layout">
      <aside class="profile-intro">
        <span class="pill"><AppIcon name="sparkles" :size="14" />MY WEATHER PROFILE</span>
        <h1>나를 알수록,<br />더 어울리는<br /><em>오늘의 옷차림.</em></h1>
        <p>한 번의 설정으로 시작하는<br />조금 더 편안한 아침.</p>
        <div class="profile-summary">
          <AppIcon name="info" :size="19" />
          <p>설정은 언제든 바꿀 수 있어요.<br />이메일과 비밀번호는 추천 모델에 전달하지 않아요.</p>
        </div>
      </aside>
      <section class="profile-editor panel">
        <div class="profile-editor-title">
          <p class="eyebrow">MAKE IT YOURS</p>
          <h2>
            {{ account.profile.location ? '나의 추천 프로필' : '먼저, 당신의 하루를 알려주세요.' }}
          </h2>
          <p class="muted">기본 정보와 추천 취향을 계정에 저장해요.</p>
        </div>
        <form @submit.prevent="submit">
          <fieldset class="form-fields" :disabled="busy">
            <label class="input-label"
              >닉네임<input
                v-model="name"
                name="name"
                autocomplete="nickname"
                required
                maxlength="100"
            /></label>
            <div class="profile-email">
              <span>가입 이메일</span><strong>{{ account.user.email }}</strong>
            </div>
            <div class="profile-location">
              <h3>주로 추천받을 지역 <span class="required-label">필수</span></h3>
              <p>현재 머무는 곳이나 자주 생활하는 지역을 선택해 주세요.</p>
              <button
                ref="regionButton"
                type="button"
                class="profile-region-button"
                @click="regionOpen = true"
              >
                <AppIcon name="pin" /><span>{{
                  location ? locationLabel(location) : '우리 동네 찾아보기'
                }}</span
                ><AppIcon name="search" :size="18" />
              </button>
              <p v-if="locationError" class="form-error" role="alert">{{ locationError }}</p>
            </div>
            <PreferenceFields v-model="preferences" />
          </fieldset>
          <div class="profile-notice">
            <AppIcon name="clock" :size="18" />
            <p>
              오늘 추천은 저장 후 선택한 조건으로 준비해요. 새로운 취향의 주간 추천은 다음 새벽
              작업에서 준비돼요.
            </p>
          </div>
          <p v-if="error" class="form-error" role="alert">
            {{ error }} <a v-if="error.includes('로그인')" href="#login">다시 로그인</a>
          </p>
          <button type="submit" class="primary-button full-width" :disabled="busy">
            <span v-if="busy" class="spinner" />{{
              busy ? '프로필을 저장하고 있어요' : '저장하고 나의 추천 보기'
            }}<AppIcon v-if="!busy" name="arrow" :size="18" />
          </button>
        </form>
      </section>
    </div>
  </main>
  <RegionPicker v-if="regionOpen" @close="regionOpen = false" @select="selectLocation" />
</template>
