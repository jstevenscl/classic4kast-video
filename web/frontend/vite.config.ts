import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      // web backend's dev port -- see WeatherStar_Video/web/backend (owned
      // by a separate agent). Matches VOD & DVR Manager's dev-proxy pattern.
      '/api': { target: 'http://localhost:8383', changeOrigin: true },
    },
  },
})
