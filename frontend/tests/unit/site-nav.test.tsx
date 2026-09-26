import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SiteNav } from "@/components/site-nav";

const pathname = vi.fn(() => "/");
vi.mock("next/navigation", () => ({ usePathname: () => pathname() }));

beforeEach(() => {
  pathname.mockReturnValue("/");
});

describe("SiteNav", () => {
  it("links Home and Models", () => {
    render(<SiteNav />);

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(screen.getByRole("link", { name: "Models" })).toHaveAttribute(
      "href",
      "/models",
    );
  });

  it("marks the current page", () => {
    pathname.mockReturnValue("/models");

    render(<SiteNav />);

    expect(screen.getByRole("link", { name: "Models" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
