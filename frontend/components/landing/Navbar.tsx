"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/utils";
import { NAV_LINKS } from "@/lib/mock-data";
import { useAuth } from "@/contexts/AuthContext";

/**
 * Sticky navigation bar. Gains a subtle border + shadow once the page
 * scrolls, per the constitution's "slightly elevated while scrolling"
 * requirement. Mobile view collapses links into a simple sheet menu.
 */
export function Navbar() {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const { user, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    const onScroll = () => setIsScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  async function handleLogout() {
    setIsMobileOpen(false);
    await logout();
    router.push("/login");
  }

  return (
    <header
      className={cn(
        "sticky top-0 z-50 w-full border-b border-transparent bg-background/95 backdrop-blur-md transition-shadow duration-200",
        isScrolled && "border-border shadow-sm",
      )}
    >
      <div className="container flex h-16 items-center justify-between">
        <Link href="/" className="flex items-center" aria-label="Speeky home">
          <Image
            src="/speeky-consolidated-logo.png"
            alt="Speeky"
            width={277}
            height={100}
            priority
            className="speeky-logo-heartbeat h-12 w-auto transition-all dark:brightness-0 dark:invert"
          />
        </Link>

        <nav aria-label="Primary" className="hidden items-center gap-8 md:flex">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-3 md:flex">
          <ThemeToggle />
          {user ? (
            <Button variant="outline" size="sm" onClick={handleLogout}>
              Logout
            </Button>
          ) : (
            <>
              <Button variant="ghost" size="sm" href="/login">
                Login
              </Button>
              <Button size="sm" href="/signup">
                Get Started
              </Button>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={() => setIsMobileOpen((open) => !open)}
          className="flex h-10 w-10 items-center justify-center rounded-xl text-foreground md:hidden"
          aria-label={isMobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={isMobileOpen}
        >
          {isMobileOpen ? (
            <X className="h-5 w-5" aria-hidden="true" />
          ) : (
            <Menu className="h-5 w-5" aria-hidden="true" />
          )}
        </button>
      </div>

      {isMobileOpen ? (
        <nav
          aria-label="Mobile"
          className="flex flex-col gap-1 border-t border-border bg-background px-6 py-4 md:hidden"
        >
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setIsMobileOpen(false)}
              className="rounded-xl px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}

          <div className="mt-2 flex flex-col gap-3 border-t border-border pt-4">
            <div className="flex items-center justify-between px-3">
              <span className="text-sm font-medium text-foreground">Theme</span>
              <ThemeToggle />
            </div>

            <div className="mt-2 flex flex-col gap-2 border-t border-border pt-3">
              {user ? (
                <Button variant="outline" size="sm" onClick={handleLogout}>
                  Logout
                </Button>
              ) : (
                <>
                  <Button variant="outline" size="sm" href="/login">
                    Login
                  </Button>
                  <Button size="sm" href="/signup">
                    Get Started
                  </Button>
                </>
              )}
            </div>
          </div>
        </nav>
      ) : null}
    </header>
  );
}
