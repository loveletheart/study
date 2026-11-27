<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, checkAdminAccess, errorMessage } from '../api'

const props = defineProps<{ signedIn: boolean }>()
const emit = defineEmits<{ close: []; login: []; expired: [] }>()
const controller = new AbortController()
const loading = ref(true)
const authorized = ref(false)
const error = ref('')

onMounted(async () => {
  try {
    const access = await checkAdminAccess(controller.signal)
    authorized.value = access.authorized === true
    if (!authorized.value) error.value = '관리자 권한이 필요합니다.'
  } catch (cause) {
    if (controller.signal.aborted) return
    if (cause instanceof ApiError && cause.status === 401 && props.signedIn) {
      emit('expired')
      return
    }
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
  }
})
onBeforeUnmount(() => controller.abort())
</script>

<template>
  <main class="profile-page">
    <header class="profile-header">
      <a class="account-brand" href="#main-content" @click.prevent="emit('close')"
        >온도<span>°</span></a
      >
      <button type="button" class="secondary-button" @click="emit('close')">
        추천으로 돌아가기
      </button>
    </header>
    <section class="profile-editor panel">
      <p v-if="loading" role="status">관리자 권한 확인 중</p>
      <template v-else-if="authorized">
        <h1>관리자 페이지</h1>
        <p class="muted">관리자 권한이 확인되었습니다.</p>
      </template>
      <template v-else>
        <h1>관리자 페이지 접근 제한</h1>
        <p class="form-error" role="alert">{{ error }}</p>
        <button v-if="!signedIn" type="button" class="secondary-button" @click="emit('login')">
          로그인
        </button>
      </template>
    </section>
  </main>
</template>
