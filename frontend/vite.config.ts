import { createReadStream, readFileSync, statSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { extname, isAbsolute, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// Chromium 90 baseline (provisional). lightningcss encodes version as major << 16.
const CHROME_90 = 90 << 16

const MODELS_DIR = fileURLToPath(new URL('./data/models', import.meta.url))
const MODEL_TYPES: Record<string, string> = {
  '.glb': 'model/gltf-binary',
  '.json': 'application/json',
}
const BOOKS_DIR = fileURLToPath(new URL('./data/books', import.meta.url))
const BOOK_TYPES: Record<string, string> = { '.pdf': 'application/pdf' }

/**
 * Serves a folder of the repo under a URL prefix (dev and preview only; the central serves them in production).
 * Only the listed file types are served, and nothing outside the folder.
 */
function serveFolder(name: string, prefix: string, dir: string, types: Record<string, string>): Plugin {
  const handler = (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const pathname = decodeURIComponent((req.url ?? '/').split('?')[0] ?? '/')
    const file = resolve(dir, `.${pathname}`)
    const inside = relative(dir, file)
    const type = types[extname(file)]
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
    name,
    configureServer: (server) => void server.middlewares.use(prefix, handler),
    configurePreviewServer: (server) => void server.middlewares.use(prefix, handler),
  }
}

const STATION_MODEL = fileURLToPath(new URL('./data/models/iss/international_space_station.glb', import.meta.url))

/**
 * Copies the ISS model into `dist/` on build, so the demo (dist embedded in the central) shows it.
 * The rest of `data/models` stays out of the build.
 */
function emitStationModel(): Plugin {
  return {
    name: 'emit-station-model',
    apply: 'build',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'models/iss/international_space_station.glb',
        source: readFileSync(STATION_MODEL),
      })
    },
  }
}

const CENTRAL_DEFAULT = 'http://localhost:8000'
const CENTRAL_PORT = '8000'

function centralTarget(raw: string | undefined): string {
  const value = raw?.trim() ?? ''
  if (value === '') return CENTRAL_DEFAULT
  const url = new URL(/^https?:\/\//.test(value) ? value : `http://${value}`)
  if (url.port === '') url.port = CENTRAL_PORT
  return url.origin
}

// .env is read here: Vite exposes it to the app only through import.meta.env, not to this config.
const CENTRAL = centralTarget(loadEnv('development', process.cwd(), '').EDGE_CENTRAL)
const centralProxy = { '/ws': { target: CENTRAL, ws: true }, '/api': { target: CENTRAL } }

export default defineConfig({
  base: './',
  plugins: [
    react(),
    serveFolder('serve-models', '/models', MODELS_DIR, MODEL_TYPES),
    serveFolder('serve-books', '/books', BOOKS_DIR, BOOK_TYPES),
    emitStationModel(),
  ],
  server: { proxy: centralProxy },
  preview: { proxy: centralProxy },
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
