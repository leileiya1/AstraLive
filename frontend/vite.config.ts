import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
// Dev server only: forward API/SSE to a local backend (scripts/run-local-isolated.sh
// listens on 18080) so `bun run dev` shares one origin with it. Builds are unaffected.
const backend = process.env.ASTRALIVE_DEV_BACKEND ?? 'http://127.0.0.1:18080'
export default defineConfig({plugins:[react(),tailwindcss()],server:{proxy:{'/api':{target:backend,changeOrigin:false},'/health':{target:backend,changeOrigin:false}}},test:{environment:'jsdom',setupFiles:['./tests/setup.ts']}})
