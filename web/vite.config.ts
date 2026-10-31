import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { backendTarget } from './backend-target.mjs'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: backendTarget(), changeOrigin: true },
    },
  },
})
