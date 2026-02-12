/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      // =====================================================
      // DESIGN TOKENS - Recall.ai Inspired Color System
      // =====================================================
      colors: {
        // Brand Colors (Recall.ai Inspired)
        brand: {
          50: '#eef6ff',
          100: '#d9ebff',
          200: '#bcdeff',
          300: '#8ecaff',
          400: '#58adff',
          500: '#478BE0',  // Primary accent
          600: '#2F61A0',  // Hover state
          700: '#1e4a7c',
          800: '#1c3d5f',
          900: '#1c3550',
          950: '#000212',  // Deep background
        },
        // Primary (alias for brand)
        primary: {
          50: '#eef6ff',
          100: '#d9ebff',
          200: '#bcdeff',
          300: '#8ecaff',
          400: '#58adff',
          500: '#478BE0',
          600: '#2F61A0',
          700: '#1e4a7c',
          800: '#1c3d5f',
          900: '#1c3550',
          950: '#000212',
        },
        // Accent (Purple/Violet)
        accent: {
          50: '#faf5ff',
          100: '#f3e8ff',
          200: '#e9d5ff',
          300: '#d8b4fe',
          400: '#c084fc',
          500: '#a855f7',
          600: '#9333ea',
          700: '#7c3aed',
          800: '#6b21a8',
          900: '#581c87',
          950: '#3b0764',
        },
        // Surface Colors (Dark Theme)
        surface: {
          DEFAULT: '#0a0f1a',
          base: '#000212',
          elevated: '#111827',
          card: '#1e293b',
          overlay: 'rgba(17, 24, 39, 0.95)',
        },
        // Content/Text Colors
        content: {
          primary: '#ffffff',
          secondary: 'rgba(255, 255, 255, 0.7)',
          tertiary: 'rgba(255, 255, 255, 0.5)',
          muted: 'rgba(255, 255, 255, 0.3)',
        },
        // Dark Theme Background (legacy support)
        dark: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#020617',
        },
        // Success
        success: {
          DEFAULT: '#22c55e',
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
        },
        // Warning
        warning: {
          DEFAULT: '#f59e0b',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
        },
        // Error
        error: {
          DEFAULT: '#ef4444',
          400: '#f87171',
          500: '#ef4444',
          600: '#dc2626',
        },
        // Info
        info: {
          DEFAULT: '#3b82f6',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
        },
      },

      // =====================================================
      // TYPOGRAPHY
      // =====================================================
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['Cal Sans', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },

      // =====================================================
      // SHADOWS (Glassmorphism)
      // =====================================================
      boxShadow: {
        'glow': '0 0 20px rgba(168, 85, 247, 0.4)',
        'glow-lg': '0 0 40px rgba(168, 85, 247, 0.3)',
        'inner-glow': 'inset 0 0 20px rgba(168, 85, 247, 0.1)',
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1)',
        'card-hover': '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1)',
      },

      // =====================================================
      // ANIMATIONS
      // =====================================================
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out',
        'fade-up': 'fadeUp 0.5s ease-out',
        'slide-in': 'slideIn 0.3s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'shimmer': 'shimmer 2s linear infinite',
        'progress': 'progress 1s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideIn: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(0)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        progress: {
          '0%': { width: '0%' },
          '50%': { width: '70%' },
          '100%': { width: '100%' },
        },
      },

      // =====================================================
      // BACKDROP BLUR
      // =====================================================
      backdropBlur: {
        xs: '2px',
      },

      // =====================================================
      // BORDER RADIUS
      // =====================================================
      borderRadius: {
        '4xl': '2rem',
        '5xl': '2.5rem',
      },

      // =====================================================
      // SPACING
      // =====================================================
      spacing: {
        '18': '4.5rem',
        '112': '28rem',
        '128': '32rem',
      },

      // =====================================================
      // Z-INDEX
      // =====================================================
      zIndex: {
        '60': '60',
        '70': '70',
        '80': '80',
        '90': '90',
        '100': '100',
      },
    },
  },
  plugins: [],
}
