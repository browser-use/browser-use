import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'Browser Use',
  description: 'Build browser agents with TypeScript. Get started with bu-pi.',
  cleanUrls: true,
  lastUpdated: false,
  head: [['link', { rel: 'icon', href: '/mark.svg', type: 'image/svg+xml' }]],
  themeConfig: {
    logo: '/mark.svg',
    siteTitle: 'Browser Use',
    nav: [
      { text: 'Docs', link: '/quickstart' },
      { text: 'API reference', link: '/api' },
      { text: 'GitHub', link: 'https://github.com/browser-use/bu-pi/tree/codex/raw-cdp-k7m2' },
    ],
    sidebar: [
      {
        text: 'Get started',
        items: [
          { text: 'Quickstart', link: '/quickstart', activeMatch: '^/(?:quickstart)?$' },
          { text: 'Models', link: '/models' },
          { text: 'Python', link: '/python' },
        ],
      },
      {
        text: 'Build with it',
        items: [
          { text: 'Sessions & login', link: '/sessions' },
          { text: 'Structured output', link: '/results' },
          { text: 'Streaming & hooks', link: '/events' },
          { text: 'Custom tools', link: '/tools' },
          { text: 'Video & GIFs', link: '/recording' },
        ],
      },
      {
        text: 'Reference',
        collapsed: true,
        items: [
          { text: 'API', link: '/api' },
          { text: 'Browser control', link: '/browser' },
          { text: 'Limits & recovery', link: '/recovery' },
          { text: 'Architecture', link: '/architecture' },
          { text: 'Migration', link: '/migration' },
          { text: 'Tests & compatibility', link: '/session-verification' },
          { text: 'Benchmarks', link: '/benchmark' },
        ],
      },
    ],
    search: { provider: 'local' },
    outline: { level: 2, label: 'On this page' },
    docFooter: { prev: 'Previous', next: 'Next' },
  },
});
