# The web app uses one warm premium light theme, set in design tokens, with serif headings

The web app shipped with shadcn's stock grayscale theme. Judges, the deck (#79) and the demo video (#80) see it first, and it looked unfinished. SPEC.md does not set a visual style. On 2026-10-02 the user approved a mockup made in Claude Design (#192) and chose the scope: theme tokens, the site shell and the key screens, light mode only.

## Decisions

- **One light theme, defined as CSS variables in `frontend/src/app/globals.css`.**
  - Palette: Ivory `#FAF9F5` background, white cards, Slate `#141413` text, Clay `#C96442` primary, Oat `#E8E4D9` borders.
  - Added tokens: `success`, `warning` and their muted fills, plus `shadow-soft` (cards) and `shadow-primary` (primary buttons).
  - The chart palette is warm, so the Recharts charts match without code changes.
  - The `.dark` block is removed, since nothing switched to it.
- **Type: Source Serif 4 for `h1`, `h2` and card titles (`--font-heading`), Geist for body text, Geist Mono for code.** All three load through `next/font`.
- **Styling lives in the shared primitives and the base layer, not in each screen.**
  - `ui/card`, `ui/button`, `ui/badge`, `ui/tabs` and `ui/input` carry the new radii, shadows and pill shapes.
  - Tables get a muted header band, small header labels and tabular figures in the base layer, so all 48 tables change together.
- **The shell and key screens get the rest:**
  - a sticky blurred nav with a logo mark and pill links;
  - a Home hero, with the composer raised in a card;
  - the agent trace drawn as a dotted timeline;
  - larger serif page titles.
- **No role, label or accessible name changes.** The unit, e2e and screenshot tests find elements by role and name. The Home `h1` stays "PromoPilot", and the mockup's headline becomes its tagline. Only the screenshot job changes: it scrolls 88 px past the sticky nav instead of 24 px.
- **The mockup's KPI strip (plan totals on the session page) is not built here.** The revision carries no totals, so the strip is a new feature that needs its own tests.

## Consequences

- A new component uses the tokens (`bg-card`, `shadow-soft`, `text-success` and the rest) and the primitives, never raw colours.
- The deck screenshots (#78/#79) are taken again after this merges.
