// @ts-check
import { defineConfig } from 'astro/config'
import react from '@astrojs/react'
import tailwindcss from '@tailwindcss/vite'

import node from '@astrojs/node';

export default defineConfig({
  output: 'server',
  integrations: [react()],

  vite: {
    plugins: [tailwindcss()],
    server: {
      proxy: {
        '/api': { target: 'http://localhost:8000', changeOrigin: true }
      }
    }
  },

  adapter: node({
    mode: 'standalone'
  })
})