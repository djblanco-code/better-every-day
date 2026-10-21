# Prompt: restyle the Job Tracker in an Apple aesthetic

Copy everything below the line and paste it to Claude.

---

Restyle `scripts/tracker_ui.html` (single file, Tailwind CDN, Lucide, Chart.js, local server on 127.0.0.1:8787) to feel like a first-party Apple app (Reminders, Notes, Calendar, the Mac System Settings window). Keep every feature and all data wiring exactly as they are. Change only look, layout, spacing, type, color and motion. Verify in the browser pane in light and dark mode at ~820px and ~1280px wide, and fix anything that overflows or misaligns before you report back.

## 1. Principles (apply in this order)

Apple HIG core principles:
- **Clarity.** Text is legible at every size, icons are precise, and the important things are visually heavier than the trivial ones. Nothing decorative that does not carry meaning.
- **Deference.** The chrome steps back so the content (my applications, counts, actions) is the subject. Soft materials, thin separators, no heavy frames.
- **Depth.** Use layers, blur and subtle shadow to show what is above what. A sheet floats; a card rests; a header is a translucent bar over scrolling content.
- **Consistency.** One spacing scale, one type scale, one radius scale, one set of controls. If two things do the same job they look the same.

Usability rules (Nielsen heuristics, Norman):
- **Visibility of system status.** Every save, sync and load shows feedback (a brief check, a spinner, a toast). Nothing changes silently.
- **Recognition over recall.** Labels say what things are. No icon without a label unless it is universal (search, close, plus).
- **Signifiers and affordances.** Clickable things look clickable (buttons, rows with chevrons); non-clickable things do not.
- **Error prevention.** Destructive actions (Remove) use a confirmation or an undo, never a bare red button next to Save.
- **Aesthetic and minimalist.** Remove anything that competes with the primary task of each screen.

Visual craft (Refactoring UI, Gestalt, Fitts):
- Build hierarchy with **weight and color before size**. Secondary text is a cooler, lighter gray, not a smaller font.
- **Spacing scale** on a 4pt base: 4, 8, 12, 16, 20, 24, 32, 40, 48. Group related items with less space, separate groups with more (proximity). Start with too much white space, then take a little away.
- **Design in grayscale first**, then add one accent color. Color marks state and action, never decoration.
- **Borders last.** Prefer background contrast, spacing or a soft shadow over a line. When a line is needed it is 1px at ~8% foreground.
- **Shadows mean elevation.** Resting card: none or a hairline. Floating sheet or popover: two layered shadows (a wide soft one plus a tight one). Nothing else casts a shadow.
- **Targets are at least 44x44pt** for anything tapped, and rows are tall enough to hit on a trackpad.

## 2. Apple visual language, concretely

Type:
- Font stack `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", Inter, system-ui, sans-serif` so Macs get San Francisco and others get Inter.
- Semantic scale modeled on Apple's text styles: Large Title 34/41 bold, Title 1 28/34 bold, Title 2 22/28 bold, Title 3 20/25 semibold, Headline 17/22 semibold, Body 17/22, Callout 16/21, Subheadline 15/20, Footnote 13/18, Caption 12/16. Body is 15 on desktop tables. Nothing below 11.
- Tight letter-spacing on titles (`-0.01em` to `-0.02em`), normal on body. Tabular numerals for all counts.

Color (system-color feel, light and dark variants for every token):
- Grouped background `#F2F2F7` / `#000000`; grouped secondary (cards) `#FFFFFF` / `#1C1C1E`; tertiary `#F2F2F7` / `#2C2C2E`.
- Label `#000` at 100/60/30/18% alpha for primary, secondary, tertiary, quaternary; invert in dark.
- Separator: label at 29% / 65% alpha (thin, not black).
- Accent: system blue `#007AFF` / `#0A84FF` by default. Keep my palette picker (blue, lavender, mint, peach) but map each to a system-style pair, for example purple `#AF52DE`/`#BF5AF2`, mint `#00C7BE`/`#63E6E2`, orange `#FF9500`/`#FF9F0A`.
- Semantic: green `#34C759`/`#30D158`, orange `#FF9500`/`#FF9F0A`, red `#FF3B30`/`#FF453A`. Use tinted fills (color at 12-16% alpha) with the solid color for text, as Apple badges do.
- Meet WCAG AA (4.5:1) on all text; check the gray-on-tint cases.

Shape and material:
- Corner radii: 10 for controls, 12 for cards and grouped lists, 16 for sheets, continuous (squircle-like) feel via `border-radius` plus a 1px inner highlight on dark.
- Concentric corners: an element inside a rounded container uses the container radius minus the padding, so curves stay parallel.
- Toolbar and header: translucent material, `backdrop-filter: saturate(180%) blur(20px)`, background at 72% alpha, hairline bottom separator.
- Cards: white (or `#1C1C1E`), no border in light mode, hairline border in dark, no drop shadow at rest.
- Lists: Apple grouped inset style. Rows 44pt min, hairline separators inset to the text edge, a chevron on rows that open something.

Controls:
- Primary button: filled accent, white text, 10pt radius, 17pt semibold on mobile, 13-15pt on desktop, no uppercase.
- Secondary: tinted accent fill (accent at 15%) with accent text. Tertiary: plain accent text.
- Segmented control for the top-level tabs (pill track, sliding white thumb with a soft shadow), not underlined tabs.
- Inputs: 10pt radius, tertiary fill, no visible border until focus, then a 2px accent ring.
- Search fields have a magnifier icon and rounded ends.
- Badges: small rounded-rect tints, 12-13pt semibold, never all caps.
- Toggles for on/off, never checkboxes, except inside tables.

Motion:
- Durations 150-250ms, ease-out for entering, ease-in for leaving. Sheets slide up 12px while fading in. Hover states shift background by one step, not color. Respect `prefers-reduced-motion`.

Icons:
- Lucide at 1.5px stroke, sized to the cap height of the adjacent text, colored with the secondary label color unless they are the control itself.

## 3. Screen by screen

- **Overview:** a Large Title "Job Tracker" with a secondary-label subtitle (date of last update). Stat tiles are a 4-up grouped grid, big tabular numbers (Title 1), label in Footnote secondary. Any "needs you" alert is a tinted orange inset banner with one clear button. Charts use the accent plus label-quaternary gridlines. The funnel card keeps its white body in both modes.
- **Action needed:** two grouped sections with section headers in Footnote uppercase secondary (Apple's grouped-list header style): "Assessments needed" and "Intro calls to set up". Each item is a row card with the company as Headline, the task as Body, meta as Footnote, and a right-aligned primary action. Due-today rows get an orange tint; overdue get red.
- **Manual applications:** the "paste a link" box is a single rounded search-style field with the button inside the trailing edge. The apply-yourself list is an inset grouped table with a leading checkbox and a trailing chevron.
- **All applications:** a toolbar row with the search field and a segmented stage filter, then a grouped table. Row click opens a sheet (not a modal) that slides up with a grabber, Cancel on the left, Done in bold accent on the right.

## 4. What not to do

- No pure black text on white; use the label alphas.
- No gradients on cards, no glow, no colored borders, no drop shadows on resting elements.
- No uppercase buttons, no bold body text, no more than one accent color on a screen.
- No new libraries, no build step, no change to the server or data files.

## 5. Report back

Show one screenshot per tab in light mode and one in dark mode, list what you changed, and list anything from this spec you could not do.
