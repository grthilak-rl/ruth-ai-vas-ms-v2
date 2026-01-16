import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  // API base URL from environment variable, with fallback for development
  const apiBaseUrl = env.VITE_API_BASE_URL || 'http://10.30.250.245:8085'

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