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
      // Elevation reads from CSS variables so light and dark each get shadows
      // tuned for their surface — a black shadow is invisible on navy.
      // sm/md keep their original names so existing markup is untouched.
      boxShadow: {
        xs: "var(--elevation-1)",
        sm: "var(--elevation-1)",
        md: "var(--elevation-2)",
        lg: "var(--elevation-3)",
        xl: "var(--elevation-4)",
        ring: "var(--elevation-ring)",
      },
      transitionTimingFunction: {
        "out-expo": "var(--ease-out-expo)",
        spring: "var(--ease-spring)",
        standard: "var(--ease-standard)",
      },
      transitionDuration: {
        instant: "var(--duration-instant)",
        fast: "var(--duration-fast)",
        normal: "var(--duration-normal)",
        slow: "var(--duration-slow)",
      },
      // Explicit type scale: previously every heading picked an ad-hoc text-*
      // size, so the same visual level rendered differently on different pages.
      fontSize: {
        display: ["clamp(2.25rem, 1.5rem + 3vw, 3.5rem)", { lineHeight: "1.05", letterSpacing: "-0.03em", fontWeight: "600" }],
        h1: ["clamp(1.75rem, 1.4rem + 1.4vw, 2.25rem)", { lineHeight: "1.15", letterSpacing: "-0.02em", fontWeight: "600" }],
        h2: ["clamp(1.375rem, 1.2rem + 0.7vw, 1.625rem)", { lineHeight: "1.25", letterSpacing: "-0.015em", fontWeight: "600" }],
        h3: ["1.125rem", { lineHeight: "1.35", letterSpacing: "-0.01em", fontWeight: "600" }],
        overline: ["0.6875rem", { lineHeight: "1.2", letterSpacing: "0.08em", fontWeight: "600" }],
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
        // Sweeping highlight for skeletons — communicates "loading", not "broken".
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        // Confidence/score reveal: bar grows from zero so progress reads as earned.
        "grow-x": {
          "0%": { transform: "scaleX(0)" },
          "100%": { transform: "scaleX(1)" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "scale(0.96)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        // Live Call caption hand-off: outgoing line fades while drifting up as if being pushed off by the incoming one.
        "fade-out-up": {
          "0%": { opacity: "1", transform: "translateY(0)" },
          "100%": { opacity: "0", transform: "translateY(-10px)" },
        },
      },
      animation: {
        "fade-up": "fade-up 300ms var(--ease-out-expo) both",
        "fade-in": "fade-in 200ms var(--ease-standard) both",
        "gradient-shift": "gradient-shift 8s ease infinite",
        "slide-in-right": "slide-in-right 250ms var(--ease-out-expo) both",
        "slide-in-left": "slide-in-left 250ms var(--ease-out-expo) both",
        shimmer: "shimmer 1.6s infinite",
        "grow-x": "grow-x 600ms var(--ease-out-expo) both",
        "scale-in": "scale-in 200ms var(--ease-spring) both",
        "fade-out-up": "fade-out-up 320ms var(--ease-standard) both",
      },
    },
  },
  plugins: [],
};

export default config;
