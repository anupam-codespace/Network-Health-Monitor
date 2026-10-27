# NetWatch Design Tokens

Comprehensive design tokens and component specification derived from Stitch UI mockups (`6014330440554392744`) for the NetWatch SPA.

## 1. Color Palette

### Surface & Background Tokens
- `--color-bg`: `#faf8ff` (Light high-contrast slate-tint surface)
- `--color-surface`: `#ffffff` (Card and panel backgrounds)
- `--color-surface-low`: `#f2f3ff` (Muted input fills and pill backdrops)
- `--color-surface-container`: `#eaedff` (Dividers, borders, and tracks)
- `--color-surface-container-high`: `#e2e7ff` (Card highlight borders)
- `--color-surface-container-highest`: `#dae2ff` (Accent containers)

### Primary & Accent Colors
- `--color-primary`: `#004ac6` (Royal Blue - main branding, links)
- `--color-primary-container`: `#2563eb` (Solid blue pills, active buttons)
- `--color-on-primary`: `#ffffff` (Text on primary)
- `--color-secondary`: `#115cba` (Secondary interactive elements)
- `--color-secondary-container`: `#669dff` (Soft secondary badge fills)

### Semantic & Status Colors
- `--color-tertiary`: `#006242` / `#007d55` (Operational emerald green)
- `--color-tertiary-bg`: `rgba(0, 125, 85, 0.12)` (Healthy chip tint)
- `--color-amber`: `#d97706` (Amber warning for cert expiry < 14 days)
- `--color-amber-bg`: `rgba(217, 119, 6, 0.12)` (Warning chip tint)
- `--color-error`: `#ba1a1a` (Failing red)
- `--color-error-bg`: `rgba(186, 26, 26, 0.12)` (Failure chip tint)

### Typography Colors
- `--color-on-surface`: `#091a3d` (Deep midnight primary text, >=7:1 contrast)
- `--color-on-surface-variant`: `#434655` (Muted secondary labels, >=4.5:1 contrast)
- `--color-outline`: `#737686` (Subtle icons and outlines)

## 2. Typography

- **Display & Headlines**: `Plus Jakarta Sans`, sans-serif (weights 600, 700, 800)
- **Body & Controls**: `Plus Jakarta Sans`, sans-serif (weights 400, 500, 600)
- **Metrics, Latency & Epochs**: `JetBrains Mono`, monospace (weights 600, 700)

### Type Scale
- `display-lg`: `48px` / `56px`, 800 weight
- `headline-lg`: `32px` / `40px`, 700 weight (Desktop) | `26px` / `34px` (Mobile)
- `headline-md`: `22px` / `30px`, 600 weight
- `headline-sm`: `18px` / `26px`, 600 weight
- `body-lg`: `16px` / `24px`, 400 weight
- `body-md`: `14px` / `20px`, 400-500 weight
- `body-sm`: `12px` / `16px`, 400-500 weight
- `label-caps`: `11px` / `14px`, 600 weight, uppercase tracking `+0.05em`
- `metric-xl`: `32px` / `36px`, 700 weight, monospace
- `metric-md`: `18px` / `24px`, 600 weight, monospace

## 3. Spatial System & Shape

### Border Radius
- `--radius-sm`: `6px` (Status dots, tags)
- `--radius-md`: `12px` (Inputs, sub-cards)
- `--radius-lg`: `20px` (Main cards, desktop outer frame)
- `--radius-full`: `9999px` (Pills, badges, round buttons)

### Touch & Accessibility Standards
- **Minimum Touch Target**: 44px × 44px for all buttons and interactive controls.
- **Safe Area Insets**: Handled via `env(safe-area-inset-top)` and `env(safe-area-inset-bottom)`.
- **Focus Indicators**: Visible 2px outline with 2px offset (`#2563eb`).
- **Contrast**: Text elements strictly maintain >= 4.5:1 contrast ratio against backdrops.
- **Color Independence**: Status is never conveyed by color alone (always paired with icon or text label).
- **Reduced Motion**: Disables transforms, transitions, and keyframe animations when `prefers-reduced-motion: reduce`.
