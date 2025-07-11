/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          100: '#dbeafe', 
          500: '#4a9eff',
          600: '#3b82f6',
          900: '#1e3a8a'
        },
        success: {
          50: '#ecfdf5',
          500: '#00d4aa',
          600: '#10b981'
        },
        warning: {
          50: '#fffbeb',
          500: '#ff8c42',
          600: '#f59e0b'
        },
        danger: {
          50: '#fef2f2',
          500: '#ff5757',
          600: '#ef4444'
        },
        purple: {
          500: '#c44eff',
          600: '#a855f7'
        },
        gray: {
          50: '#f9fafb',
          100: '#f3f4f6',
          800: '#1f2937',
          900: '#111827',
          950: '#0f0f0f'
        }
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', 'sans-serif'],
        'mono': ['JetBrains Mono', 'monospace']
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-soft': 'pulseSoft 2s infinite',
        'bounce-soft': 'bounceSoft 1s infinite'
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' }
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' }
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.8' }
        },
        bounceSoft: {
          '0%, 20%, 50%, 80%, 100%': { transform: 'translateY(0)' },
          '40%': { transform: 'translateY(-4px)' },
          '60%': { transform: 'translateY(-2px)' }
        }
      },
      backdropBlur: {
        'xs': '2px'
      },
      boxShadow: {
        'glow': '0 0 20px rgba(74, 158, 255, 0.3)',
        'glow-green': '0 0 20px rgba(0, 212, 170, 0.3)',
        'glow-red': '0 0 20px rgba(255, 87, 87, 0.3)'
      }
    },
  },
  plugins: [],
} 