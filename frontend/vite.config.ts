import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [react()],

    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
          configure: (proxy, options) => {
            console.log('Configuring proxy with target:', options.target);
            proxy.on('error', (err, req, res) => {
              console.log('proxy error', err);
            });
            proxy.on('proxyReq', (proxyReq, req, res) => {
              console.log('Proxying request:', req.method, req.url, '-> target:', options.target);
            });
            proxy.on('proxyRes', (proxyRes, req, res) => {
              console.log('Received response:', proxyRes.statusCode, req.url);
            });
          },
        },
      },
    },

    build: {
      sourcemap: false,
    },
  }
})