# Dependency vulnerability risk register

This register records unresolved dependency findings. Review it on every dependency change and before each release. New high or critical findings block release unless a time-bounded exception is approved.

| Ecosystem | Package/advisory | Severity | NewsCraft exposure and mitigation | Classification | Owner/follow-up | Review/expiry |
| --- | --- | --- | --- | --- | --- | --- |
| Frontend | `postcss <8.5.10`, GHSA-qx2v-qp2m-jg93, two audit paths (direct build dependency and Next.js) | Moderate | The issue is unsafe CSS stringification of an unescaped `</style>`. NewsCraft does not accept user-authored CSS, and the production runner contains compiled output rather than the build toolchain. `npm audit fix --force` proposes the incompatible Next.js 9.3.3 downgrade, so it is prohibited. Upgrade the owning compatible Next/PostCSS graph in an isolated change. | Temporarily accepted; not exposed by current product inputs | Frontend maintainer; isolated Next/PostCSS update | 2026-08-19 |

The Phase 8 report records the exact audit command, advisory identifiers, and whether this provisional row remains necessary. Never place vulnerability payloads containing credentials or private registry URLs in this file.
