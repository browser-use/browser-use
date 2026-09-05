import { defineConfig } from 'vitepress';
export default defineConfig({
  title: 'Browser Use / next',
  description:
    'A small JavaScript SDK for capable web agents. Pi models, persistent code, real browsers.',
  cleanUrls: true,
  lastUpdated: false,
  head: [['link', { rel: 'icon', href: '/mark.svg', type: 'image/svg+xml' }]],
  themeConfig: {
    logo: '/mark.svg',
    siteTitle: 'browser use',
    nav: [
      { text: 'Documentation', link: '/quickstart' },
      { text: 'Design decisions', link: '/architecture' },
      { text: 'Verification', link: '/verification' },
    ],
    sidebar: [
      {
        text: 'START BUILDING',
        items: [
          { text: 'Quickstart', link: '/quickstart' },
          { text: 'Models & providers', link: '/models' },
          { text: 'Typed results', link: '/results' },
        ],
      },
      {
        text: 'TAKE CONTROL',
        items: [
          { text: 'Browser & JavaScript', link: '/browser' },
          { text: 'Custom tools & events', link: '/tools' },
          { text: 'Limits & recovery', link: '/recovery' },
        ],
      },
      {
        text: 'UNDER THE HOOD',
        items: [
          { text: 'Design decisions', link: '/architecture' },
          { text: 'Migration & scope', link: '/migration' },
          { text: 'Verification', link: '/verification' },
          { text: 'Hard benchmark', link: '/benchmark' },
          { text: 'API reference', link: '/api' },
        ],
      },
    ],
    search: { provider: 'local' },
    outline: { level: [2, 3] },
    footer: {
      message: 'Prototype · v0.1.0 · Not published to npm',
      copyright: 'Built on Pi and raw CDP. MIT licensed.',
    },
  },
});
