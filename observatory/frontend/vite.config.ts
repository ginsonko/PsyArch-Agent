import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/next/',
  build: {
    outDir: '../web_static_next',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1400,
    rollupOptions: {
      output: {
        manualChunks: {
          mantine: ['@mantine/core', '@mantine/hooks'],
          charts: ['echarts', 'echarts-for-react'],
          table: ['@tanstack/react-table', '@tanstack/react-virtual'],
          editor: ['@monaco-editor/react'],
          flow: ['reactflow'],
        },
      },
    },
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
});
