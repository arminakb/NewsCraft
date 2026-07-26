# Accessibility release verification

Automated CI runs the mocked Chromium accessibility suite at 390×844 and 1440×1000 in light and dark themes. Diagnostics includes a real error-attention fixture, and serious/critical Axe findings block `release-gate`. Semantic error, warning, success, and neutral badges use explicit foreground/background/focus pairs protected by numeric contrast tests.

Before production release, retain evidence for this manual checklist on healthy hardware:

- keyboard-only traversal: skip link, one page heading, review/action links, visible focus, no trap;
- 200% and 400% zoom/reflow: no information or action loss and no horizontal page scrolling;
- forced-colors mode: status text and borders remain visible without color dependence;
- reduced-motion mode: no required information depends on animation;
- Persian/RTL attention title: reading order and action name remain understandable;
- NVDA or VoiceOver: status labels and timestamps are announced once; decorative icons stay silent.

Record browser/OS/screen-reader versions, viewport/theme, Axe JSON, screenshots of each status palette, and any exception with owner and expiry. Do not mark this checklist complete from class-name or JSDOM tests alone.
