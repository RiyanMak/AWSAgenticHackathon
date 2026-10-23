# Design: Course

CareRelay's visual system for the patient UI and the deck, chosen from six directions on 2026-10-23 (Impeccable concept roll, operate mode, seed reference `seed:7c420acfb37a4de9`). Product facts live in [PRODUCT.md](PRODUCT.md); implementation and agent contracts in [docs/FRONTEND.md](docs/FRONTEND.md).

## Idea

An orienteering map. The reports are the **terrain**, a fixed colour language that the patient reads but nobody edits. What to do about them is the **course**: numbered controls joined by a purple line that rides over everything, punched when done. Agents are controls on the same course, so the handoffs between them are visible legs. The course separates what the reports say from what you do about it, which is the product's core idea.

## Tokens

Source of truth: [design/tokens.json](design/tokens.json), generated into `src/carerelay/ui/www/tokens.css` (CSS custom properties) and `presentation/_tokens.scss` (SCSS variables) by `python design/build_tokens.py`.

| Role | Token | Value | Use |
|---|---|---|---|
| Ground | `color-ground` | #ffffff | Page; "runnable" white |
| Terrain | `color-terrain` | #f6f7f1 | Map and input panels |
| Ink | `color-ink` | #1c1c1a | Text, table header rules |
| Muted | `color-muted` | #5a5a52 | Secondary text (7:1 on white) |
| Rule | `color-rule` | #e2e2da | Row dividers |
| Course | `color-course` | #a1238a | The route, controls, primary action, selection. Reserved: nothing decorative is purple |
| Course tint | `color-course-tint` | #f6e6f2 | Punched or current control fill |
| Contour | `color-contour` | #b5651d | Thin contour lines on map grounds only |
| Thicket / Open / Water | `color-thicket` / `color-open` / `color-water` | #8ea64a / #f2d16b / #2b7bb9 | Ledger symbols: book soon / mention to PCP / answered |
| Urgent | `color-urgent` | #c62828 | Urgent findings and agent errors only |
| Pending | `color-pending` | #9a9a90 | Waiting controls and dashed unrun legs |

Type: **Archivo** for UI and headings, **Archivo Narrow** for the wordmark, control numbers, table headers and other numerals (tabular figures). Radius 6px. Course legs 3.5px (UI) and 4.5px (deck).

## Components

- **Control**: circle with the step number; states waiting (grey), working (thick purple), done (tinted, tick), demo (dashed purple), not built (dotted grey), error (red). Start is a triangle, finish ("You") a double circle.
- **Leg**: grey dashed until its source agent is done, then solid purple; a leg flows (moving dash) only while a handoff is in flight. This is the one authored motion; it stops under `prefers-reduced-motion`.
- **Control description table**: numbered rows, narrow header with a 2px ink rule, tabular numbers right-aligned. Used for agent tasks and for appointments.
- **Ledger row**: small square map symbol in the triage colour, title, triage label, plain text, owner.
- **Ruled-out option**: struck through in course purple with the reason below.

## Rules

- Purple means "the course": route, current step, primary action. Never decoration.
- No eyebrow labels above headings, no side-stripe cards, no gradient text, no emoji icons; icons are drawn SVG.
- Patient's answer first. On phones the result renders above the agent course.
- Every number comes from an agent or tool; demo data is labelled as such.
- Contrast: body and secondary text at least 4.5:1 on ground and terrain.
