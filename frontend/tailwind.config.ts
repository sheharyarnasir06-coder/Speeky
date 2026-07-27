const config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: {
        "2xl": "1280px",
      },
    },
    extend: {
      colors: {
        background: "hsl(var(--background))",
        surface: {
          DEFAULT: "hsl(var(--surface))",
          elevated: "hsl(var(--surface-elevated))",
        },
        foreground: "hsl(var(--foreground))",
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          hover: "hsl(var(--primary-hover))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
        danger: "hsl(var(--danger))",
        info: "hsl(var(--info))",
      },
      borderRadius: {
        xl: "0.75rem",
        "2xl": "1rem",
      },
      fontFamily: {
        sans: ["var(--font-body)", "system-ui", "sans-serif"],
        serif: ["var(--font-heading)", "Georgia", "serif"],
        heading: ["var(--font-heading)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        sm: "0 1px 2px 0 rgb(15 23 42 / 0.04)",
        md: "0 4px 12px -2px rgb(15 23 42 / 0.08)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "gradient-shift": {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        "slide-in-right": {
          "0%": { opacity: "0", transform: "translateX(16px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        "slide-in-left": {
          "0%": { opacity: "0", transform: "translateX(-16px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 300ms ease-out both",
        "fade-in": "fade-in 200ms ease-out both",
        "gradient-shift": "gradient-shift 8s ease infinite",
        "slide-in-right": "slide-in-right 250ms ease-out both",
        "slide-in-left": "slide-in-left 250ms ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
