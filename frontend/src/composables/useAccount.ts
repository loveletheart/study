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

export function useAccount() {
  const account = ref<Account | null>(null)
  const ready = ref(false)
  const busy = ref(false)
  const error = ref('')
  const controller = new AbortController()
  let generation = 0
  async function restore() {
    const current = ++generation
    try {
      const value = await getAccount(controller.signal)
      if (current === generation) account.value = value
    } catch (cause) {
      if (!(cause instanceof ApiError && cause.code === 'AUTH_REQUIRED'))
        error.value = errorMessage(cause)
    } finally {
      if (current === generation) ready.value = true
    }
  }
  async function action(work: () => Promise<Account | null>) {
    if (busy.value) return false
    generation++
    busy.value = true
    error.value = ''
    try {
      account.value = await work()
      ready.value = true
      return true
    } catch (cause) {
      error.value = errorMessage(cause)
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
    action(() => updateProfile(values, controller.signal))
  const signOut = () =>
    action(async () => {
      await logoutAccount(controller.signal)
      return null
    })
  onBeforeUnmount(() => controller.abort())
  void restore()
  return { account, ready, busy, error, signIn, saveProfile, signOut }
}
