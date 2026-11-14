import { createReadStream, statSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { extname, isAbsolute, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// Chromium 90 baseline (provisional). lightningcss encodes version as major << 16.
const CHROME_90 = 90 << 16

const MODELS_DIR = fileURLToPath(new URL('./data/models', import.meta.url))
const MODEL_TYPES: Record<string, string> = {
  '.glb': 'model/gltf-binary',
  '.json': 'application/json',
}

/** Serves `data/models` at `/models` (dev and preview only; the central serves it in production). */
function serveModels(): Plugin {
  const handler = (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const pathname = decodeURIComponent((req.url ?? '/').split('?')[0] ?? '/')
    const file = resolve(MODELS_DIR, `.${pathname}`)
    const inside = relative(MODELS_DIR, file)
    const type = MODEL_TYPES[extname(file)]
    if (!type || inside.startsWith('..') || isAbsolute(inside)) return next()
    try {
      const stats = statSync(file)
      if (!stats.isFile()) return next()
      res.setHeader('Content-Type', type)
      res.setHeader('Content-Length', stats.size)
      createReadStream(file).pipe(res)
    } catch {
      next()
    }
  }
  return {
    name: 'serve-models',
    configureServer: (server) => void server.middlewares.use('/models', handler),
    configurePreviewServer: (server) => void server.middlewares.use('/models', handler),
  }
}

export default defineConfig({
  base: './',
  plugins: [react(), serveModels()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  css: {
    transformer: 'lightningcss',
    lightningcss: {
      targets: { chrome: CHROME_90 },
      cssModules: { pattern: '[local]_[hash]' },
    },
  },
  build: {
    target: 'chrome90',
    cssMinify: 'lightningcss',
    sourcemap: false,
  },
})
