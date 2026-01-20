import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // API base URL for Ruth AI backend (port 8090)
  // Note: VAS backend is on port 8085, but Ruth AI frontend calls Ruth AI backend
  const apiBaseUrl = env.VITE_API_BASE_URL || 'http://localhost:8090'

  return {
    plugins: [react()],
    server: {
      port: 3300,
      host: '0.0.0.0',
      proxy: {
        '/api': {
          target: apiBaseUrl,
          changeOrigin: true,
        },
        '/v2': {
          target: apiBaseUrl,
          changeOrigin: true,
        },
        '/health': {
          target: apiBaseUrl,
          changeOrigin: true,
        },
      },
    },
  }
})