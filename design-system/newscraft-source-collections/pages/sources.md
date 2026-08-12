# Sources Page Overrides

> **PROJECT:** NewsCraft Source Collections
> **Generated:** 2026-08-06 23:56:41
> **Page Type:** Dashboard / Data View

> ⚠️ **IMPORTANT:** Rules in this file **override** the Master file (`design-system/MASTER.md`).
> Only deviations from the Master are documented here. For all other rules, refer to the Master.

---

## Page-Specific Rules

### Layout Overrides

- **Max Width:** 1200px (standard)
- **Layout:** Full-width sections, centered content
- **Sections:** 1. Hero (product + live preview or status), 2. Key metrics/indicators, 3. How it works, 4. CTA (Start trial / Contact)

### Spacing Overrides

- No overrides — use Master spacing

### Typography Overrides

- No overrides — use Master typography

### Color Overrides

- **Strategy:** Dark or neutral. Status colors (green/amber/red). Data-dense but scannable.

### Component Overrides

- Avoid: Leave UI frozen with no feedback
- Avoid: Use arbitrary large z-index values
- Avoid: Desktop-first causing mobile issues

---

## Page-Specific Components

- No unique components for this page

---

## Recommendations

- Effects: Deal movement animations, metric updates, leaderboard ranking changes, gauge needle movements, status change highlights
- Animation: Use skeleton screens or spinners
- Layout: Define z-index scale system (10 20 30 50)
- Responsive: Start with mobile styles then add breakpoints
- CTA Placement: Primary CTA in nav + After metrics
