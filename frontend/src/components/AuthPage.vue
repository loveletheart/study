<script setup lang="ts">
import { ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import WardrobeArt from './WardrobeArt.vue'
const props = defineProps<{ mode: 'login' | 'register'; busy: boolean; error: string }>()
const emit = defineEmits<{
  submit: [values: { email: string; password: string; name?: string }]
  navigate: [view: 'home' | 'login' | 'register']
}>()
const name = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const showPassword = ref(false)
const validation = ref('')
watch(
  () => props.mode,
  () => {
    password.value = ''
    confirm.value = ''
    validation.value = ''
  },
)
function submit() {
  validation.value = ''
  if (props.mode === 'register' && password.value !== confirm.value) {
    validation.value = '비밀번호가 서로 달라요. 다시 확인해 주세요.'
    return
  }
  emit('submit', {
    email: email.value.trim(),
    password: password.value,
    ...(props.mode === 'register' ? { name: name.value.trim() } : {}),
  })
}
</script>

<template>
  <main class="account-layout auth-layout">
    <section class="account-story">
      <a class="account-brand" href="#main-content" @click.prevent="emit('navigate', 'home')"
        >온도<span>°</span></a
      >
      <p class="eyebrow">A WARDROBE THAT KNOWS YOU</p>
      <h1>오늘의 날씨에,<br />당신을 더해요.</h1>
      <p>매번 다시 고를 필요 없이.<br />나의 지역과 취향으로 준비하는 하루.</p>
      <div class="account-art"><WardrobeArt /></div>
      <span class="account-story-caption">WEAR THE WEATHER, YOUR WAY.</span>
    </section>
    <section class="account-form-side">
      <button class="text-button account-back" @click="emit('navigate', 'home')">
        <AppIcon name="arrow" :size="16" />둘러보기로 돌아가기
      </button>
      <div class="auth-form-wrap">
        <span class="small-label"><AppIcon name="leaf" :size="14" />나만의 데일리 가이드</span>
        <h2>{{ mode === 'login' ? '다시 만나 반가워요.' : '나를 위한 온도, 시작해요.' }}</h2>
        <p class="muted">
          {{
            mode === 'login'
              ? '저장해 둔 지역과 취향을 이어서 만나보세요.'
              : '간단한 가입 후 나에게 맞는 추천을 설정해요.'
          }}
        </p>
        <div class="auth-tabs">
          <button
            :class="{ selected: mode === 'login' }"
            :aria-pressed="mode === 'login'"
            @click="emit('navigate', 'login')"
          >
            로그인</button
          ><button
            :class="{ selected: mode === 'register' }"
            :aria-pressed="mode === 'register'"
            @click="emit('navigate', 'register')"
          >
            회원가입
          </button>
        </div>
        <form @submit.prevent="submit">
          <fieldset class="form-fields" :disabled="busy">
            <label v-if="mode === 'register'" class="input-label"
              >닉네임<input
                v-model="name"
                name="name"
                autocomplete="nickname"
                required
                minlength="1"
                maxlength="100"
                placeholder="어떻게 불러드릴까요?" /></label
            ><label class="input-label"
              >이메일<input
                v-model="email"
                type="email"
                name="email"
                autocomplete="username"
                required
                maxlength="254"
                placeholder="your@email.com"
            /></label>
            <div class="input-label">
              <label for="auth-password">비밀번호</label>
              <div class="password-field">
                <input
                  v-model="password"
                  id="auth-password"
                  :type="showPassword ? 'text' : 'password'"
                  name="password"
                  :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
                  required
                  :minlength="mode === 'register' ? 10 : 1"
                  maxlength="128"
                  :placeholder="
                    mode === 'register' ? '10자 이상으로 입력해 주세요' : '비밀번호를 입력해 주세요'
                  "
                /><button
                  type="button"
                  class="password-toggle"
                  :aria-pressed="showPassword"
                  :aria-label="showPassword ? '비밀번호 숨기기' : '비밀번호 표시'"
                  @click="showPassword = !showPassword"
                >
                  {{ showPassword ? '숨김' : '보기' }}
                </button>
              </div>
            </div>
            <label v-if="mode === 'register'" class="input-label"
              >비밀번호 확인<input
                v-model="confirm"
                type="password"
                name="confirm"
                autocomplete="new-password"
                required
                minlength="10"
                maxlength="128"
                placeholder="한 번 더 입력해 주세요"
            /></label>
          </fieldset>
          <p v-if="validation || error" class="form-error" role="alert">
            {{ validation || error }}
          </p>
          <button class="primary-button full-width auth-submit" :disabled="busy" type="submit">
            <span v-if="busy" class="spinner" />{{
              busy ? '확인하고 있어요' : mode === 'login' ? '로그인하기' : '가입하고 취향 설정하기'
            }}<AppIcon v-if="!busy" name="arrow" :size="18" />
          </button>
        </form>
        <p class="auth-footnote">
          {{
            mode === 'register'
              ? '다음 단계에서 지역·체감 온도·스타일을 설정해요. 선호 의류와 피할 옷은 선택 사항이에요.'
              : '계정 없이도 둘러볼 수 있어요. 로그인하면 나의 추천 설정을 계정에 저장할 수 있어요.'
          }}
        </p>
      </div>
      <p class="account-form-footer">오늘의 온도에, 나다운 하루를.</p>
    </section>
  </main>
</template>
