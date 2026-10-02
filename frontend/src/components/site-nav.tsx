"use client";

import { TrendingUp } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/models", label: "Models" },
  { href: "/data", label: "Data" },
  { href: "/evals", label: "Evals" },
];

export function SiteNav() {
  const pathname = usePathname();
  return (
    <header className="bg-background/85 sticky top-0 z-40 border-b backdrop-blur-md">
      <nav
        aria-label="Main"
        className="mx-auto flex h-16 w-full max-w-screen-2xl items-center gap-8 px-8 text-sm"
      >
        <span className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="bg-primary text-primary-foreground shadow-primary flex size-8 items-center justify-center rounded-[9px]"
          >
            <TrendingUp className="size-4" strokeWidth={2.4} />
          </span>
          <span className="font-heading text-xl font-semibold tracking-tight">
            PromoPilot
          </span>
        </span>
        <div className="flex items-center gap-1">
          {LINKS.map(({ href, label }) => {
            const current = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "rounded-full px-3.5 py-1.5 transition-colors",
                  current
                    ? "bg-secondary text-foreground font-medium"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {label}
              </Link>
            );
          })}
        </div>
      </nav>
    </header>
  );
}
