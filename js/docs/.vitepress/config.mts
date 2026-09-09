import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'Browser Use JS',
  description: 'Pi, with a browser. Persistent JavaScript and raw CDP.',
  cleanUrls: true,
  themeConfig: {
    logo: '/mark.svg',
    nav: [{ text: 'GitHub', link: 'https://github.com/browser-use/bu-pi/tree/codex/raw-cdp-k7m2' }],
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
