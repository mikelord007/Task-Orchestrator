# Task Orchestrator identity

Original mark designed in the `gpt-6-astra` runtime for the dark technical Modernist brief. The old command-key glyph and hierarchy icon are replaced by two offset square frames with one open passage. The outer frame gives work a common boundary; the inner frame suggests a task moving through it. The asymmetry remains recognizable without letters or color coding.

## Assets

Paths below are relative to `frontend/public/brand/`; applications serve them at `/brand/`.

| File | ViewBox | Use |
| --- | --- | --- |
| `task-orchestrator-mark.svg` | `0 0 32 32` | Compact navigation, 24 or 32 px preferred; 16 px minimum |
| `task-orchestrator-lockup.svg` | `0 0 252 32` | Horizontal brand, 252 × 32 px preferred; 220.5 × 28 px minimum |
| `task-orchestrator-wordmark.svg` | `0 0 208 32` | Standalone horizontal name, 208 × 32 px preferred |
| `task-orchestrator-favicon.svg` | `0 0 32 32` | Same pixel-aligned mark with opaque square `#131211` field for browser tabs |

The mark is two original filled, orthogonal paths on a 4-unit grid. Its shortest strokes and openings are 2 px at 16 px, 3 px at 24 px, and 4 px at 32 px. Display mark-only artwork at multiples of 8 px with integer pixel placement. Preserve the viewBox and aspect ratio. Keep at least 4 viewBox units of external clear space; the assets already include 4 units of vertical internal clearance. Use the mark alone when the lockup cannot fit at its minimum size; do not squeeze the lettering.

All artwork uses exact `#f3f2f2` ink. Only the favicon adds `#131211`. The transparent assets belong on the specified dark grounds. No red brand state, rounded containers, gradients, shadows, strokes, or bitmap dependencies. App focus indicators remain the frontend's responsibility.

The uppercase wordmark is JetBrains Mono Medium (500), 20-unit em, converted to paths from the Google Fonts `ofl/jetbrainsmono/JetBrainsMono[wght].ttf` source. It has no runtime font dependency. Its curves are the typeface's letterforms; the architectural mark has only right angles. The font's OFL notice is retained in `JetBrainsMono-OFL.txt`. Surrounding UI/headings use Archivo 400/600/700/800; technical labels use JetBrains Mono 400/500/700. The specimen loads these two families from Google Fonts; SVG rendering itself is entirely self-contained.

## Integration examples

```html
<a href="/" aria-label="Task Orchestrator home">
  <img src="/brand/task-orchestrator-lockup.svg" width="252" height="32" alt="">
</a>

<!-- Standalone image: supply the name on the embedding image. -->
<img src="/brand/task-orchestrator-mark.svg" width="32" height="32" alt="Task Orchestrator">

<link rel="icon" href="/brand/task-orchestrator-favicon.svg" type="image/svg+xml">
```

Each SVG also includes `role="img"`, a title, and a description. Prefer image embedding. If embedding the SVG markup inline more than once, give each title/description pair unique IDs and update `aria-labelledby`. A mark beside an already named wordmark/link should be decorative (`aria-hidden="true"` for inline SVG or empty `alt` for `img`).

## Verification and ownership

Open `docs/brand/specimen.html` with `ao preview docs/brand/specimen.html`. It shows the horizontal lockup, actual-size 16/24/32/48 px samples, and dark surface comparisons. XML/accessibility checks and path-bound checks pass for every SVG; all mark coordinates align to whole pixels at those four sizes.

Computed ink contrast: 16.75:1 on `#131211`, 17.48:1 on `#0d0c0c`, 15.55:1 on `#1b1a19`, and 14.35:1 on `#232120`.

This handoff adds isolated assets and documentation only. Frontend worker `task-orchestrator-24` owns landing/dashboard references and favicon metadata integration. Local-only delivery; no push, PR, or production publishing.

AO Browser opened the specimen successfully; its snapshot identifies the specimen sections and both console/page-error reports are empty. Screenshot capture timed out twice (`Page.captureScreenshot`), so a screenshot-based visual review remains unverified in this session.
