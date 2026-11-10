import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端统一使用相对 API 地址，开发和预览服务都转发到本机后端。
const proxy = { '/api': 'http://127.0.0.1:8000' }

export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
})
