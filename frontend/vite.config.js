import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ['.trycloudflare.com', '.loca.lt', 'localhost'],
    proxy: {
      '/api': 'http://localhost:5001',
    },
  },
})
