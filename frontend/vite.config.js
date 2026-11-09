import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  // 백엔드의 비밀 설정을 클라이언트 번들로 가져오지 않는다.
  const env = loadEnv(mode, process.cwd(), 'STUDY_API_TARGET')
  const proxy = {
    '/api': { target: env.STUDY_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
  }
  return {
    base: '/app/',
    plugins: [vue()],
    server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
  }
})
