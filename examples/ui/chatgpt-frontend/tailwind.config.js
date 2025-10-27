/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        'chatgpt-gray': {
          50: '#f7f7f8',
          100: '#ececf1',
          200: '#d9d9e3',
          700: '#40414f',
          800: '#343541',
          900: '#202123',
        },
      },
    },
  },
  plugins: [],
}
