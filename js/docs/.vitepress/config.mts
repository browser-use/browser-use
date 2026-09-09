import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'Browser Use Pi',
  description: 'Browser Use, built on Pi. Persistent V8 REPL + raw CDP, in TypeScript.',
  cleanUrls: true,
  themeConfig: {
    logo: '/mark.svg',
    nav: [{ text: 'GitHub', link: 'https://github.com/browser-use/browser-use-pi/tree/main' }],
    sidebar: [
      { text: 'Quickstart', link: '/quickstart' },
      { text: 'Models', link: '/models' },
      { text: 'Browser primitives', link: '/browser' },
      { text: 'Sessions & login', link: '/sessions' },
      { text: 'API', link: '/api' },
      { text: 'Python', link: '/python' },
      { text: 'Historical benchmarks', link: '/benchmarks' },
    ],
    search: { provider: 'local' },
  },
});
