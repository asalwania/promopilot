"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

// `/evals` and `/data` join this list when they exist (ADR 0030).
const LINKS = [
  { href: "/", label: "Home" },
  { href: "/models", label: "Models" },
];

export function SiteNav() {
  const pathname = usePathname();
  return (
    <header className="border-b">
      <nav
        aria-label="Main"
        className="mx-auto flex w-full max-w-6xl items-center gap-6 px-8 py-3 text-sm"
      >
        <span className="font-semibold">PromoPilot</span>
        {LINKS.map(({ href, label }) => {
          const current = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={current ? "page" : undefined}
              className={cn(
                "hover:underline",
                current ? "font-medium" : "text-muted-foreground",
              )}
            >
              {label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
