import { onBeforeUnmount, ref } from 'vue'
import {
  ApiError,
  authenticate,
  errorMessage,
  getAccount,
  logoutAccount,
  updateProfile,
} from '../api'
import type { Account, ProfileInput } from '../types'

const sessionMarker = 'ondo.signed-in.v1'

export function useAccount() {
  const account = ref<Account | null>(null)
  const ready = ref(false)
  const busy = ref(false)
  const error = ref('')
  const sessionExpired = ref(false)
  const controller = new AbortController()
  let generation = 0

  function rememberAccount(value: Account | null) {
    account.value = value
    try {
      if (value) localStorage.setItem(sessionMarker, '1')
      else localStorage.removeItem(sessionMarker)
    } catch {
      // 저장소를 사용할 수 없어도 현재 세션은 서버 응답으로 확인한다.
    }
  }

  function hadSession() {
    try {
      return localStorage.getItem(sessionMarker) === '1'
    } catch {
      return false
    }
  }

  function expireSession() {
    generation++
    rememberAccount(null)
    sessionExpired.value = true
    ready.value = true
  }

  async function restore() {
    const current = ++generation
    try {
      const value = await getAccount(controller.signal)
      if (current === generation) rememberAccount(value)
    } catch (cause) {
      if (current !== generation) return
      if (
        cause instanceof ApiError &&
        (cause.code === 'AUTH_SESSION_EXPIRED' || (cause.code === 'AUTH_REQUIRED' && hadSession()))
      ) {
        expireSession()
      } else if (!(cause instanceof ApiError && cause.code === 'AUTH_REQUIRED')) {
        error.value = errorMessage(cause)
      }
    } finally {
      if (current === generation) ready.value = true
    }
  }
  async function action(work: () => Promise<Account | null>, requiresSession = false) {
    if (busy.value) return false
    const current = ++generation
    busy.value = true
    error.value = ''
    try {
      const value = await work()
      if (current !== generation) return false
      rememberAccount(value)
      sessionExpired.value = false
      ready.value = true
      return true
    } catch (cause) {
      if (current === generation) {
        if (requiresSession && cause instanceof ApiError && cause.status === 401) expireSession()
        else error.value = errorMessage(cause)
      }
      return false
    } finally {
      busy.value = false
    }
  }
  const signIn = (
    mode: 'login' | 'register',
    values: { email: string; password: string; name?: string },
  ) => action(() => authenticate(mode, values, controller.signal))
  const saveProfile = (values: ProfileInput) =>
    action(() => updateProfile(values, controller.signal), true)
  const signOut = () =>
    action(async () => {
      await logoutAccount(controller.signal)
      return null
    })
  onBeforeUnmount(() => controller.abort())
  void restore()
  return {
    account,
    ready,
    busy,
    error,
    sessionExpired,
    expireSession,
    signIn,
    saveProfile,
    signOut,
  }
}
