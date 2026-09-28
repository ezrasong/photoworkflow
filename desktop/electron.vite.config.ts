// Adapted from OpenCode packages/desktop/electron.vite.config.ts; see UPSTREAM.md.
import { defineConfig } from 'electron-vite'
import solid from 'vite-plugin-solid'
export default defineConfig({
  main: {build:{rollupOptions:{input:{index:'src/main/index.ts'}}}},
  preload: {build:{rollupOptions:{input:{index:'src/preload/index.ts'},output:{format:'cjs',entryFileNames:'[name].js'}}}},
  renderer: {root:'src/renderer',plugins:[solid()],build:{rollupOptions:{input:{main:'src/renderer/index.html'}}}}
})
