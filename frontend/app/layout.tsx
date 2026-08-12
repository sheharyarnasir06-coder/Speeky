import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "./providers";
import { SpeekyBirdCompanion } from "@/components/common/SpeekyBirdCompanion";

// Configure Fraunces for premium, classic headings
const fraunces = localFont({
  src: "./fonts/Fraunces.ttf",
  variable: "--font-heading",
  display: "swap",
});

// Configure Mulish for clean, minimalist body text
const mulish = localFont({
  src: "./fonts/Mulish.ttf",
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Speeky — AI Communication Coach",
  description:
    "Speeky is an AI communication coach that helps you speak with confidence in interviews, meetings, and everyday conversations.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      // Inject both font variables into the HTML layer
      className={`${fraunces.variable} ${mulish.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <script
          dangerouslySetInnerHTML={{
            __html: `
          try {
            const theme = localStorage.getItem('speeky-theme');
            if (theme === 'dark') {
              document.documentElement.classList.add('dark');
            }
          } catch {}
        `,
          }}
        />
        <Providers>
          {children}
          <SpeekyBirdCompanion />
        </Providers>
      </body>
    </html>
  );
}
