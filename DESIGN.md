---
name: Orchestra
description: Local-first agent orchestration that shows you exactly what left your machine.
colors:
  ink-ground: "#14100f"
  ink-panel: "#191413"
  ink-raised: "#1e1817"
  ink-well: "#241d1b"
  rule: "#352926"
  rule-lit: "#4c3b36"
  stock: "#e9e2d5"
  stock-rule: "#b9ae9b"
  stock-ink: "#1a1513"
  text-primary: "#f0e8dd"
  text-secondary: "#bdb0a3"
  text-tertiary: "#8f8175"
  channel-green: "#56b47a"
  channel-green-dim: "#2b4a39"
  channel-red: "#d75046"
  channel-red-dim: "#4d2724"
  channel-amber: "#dda03a"
  channel-amber-dim: "#4a3a1e"
  brand-gold: "#d9c48c"
  brand-gold-dim: "#4a3f28"
  slip-head: "#5c5044"
  slip-label: "#6b5f52"
  slip-foot: "#ded6c7"
  slip-green: "#2f7a4e"
  slip-red: "#a83228"
typography:
  display:
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace"
    fontSize: "32px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.22em"
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-0.01em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  prose:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  caption:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  label:
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.14em"
  data:
    fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0.06em"
rounded:
  edge: "2px"
  panel: "3px"
  full: "50%"
spacing:
  hairline: "4px"
  tight: "8px"
  snug: "10px"
  base: "14px"
  panel: "16px"
  loose: "22px"
  section: "28px"
components:
  button-primary:
    backgroundColor: "{colors.ink-raised}"
    textColor: "{colors.brand-gold}"
    typography: "{typography.label}"
    rounded: "{rounded.edge}"
    padding: "8px 14px"
  button-primary-hover:
    backgroundColor: "{colors.brand-gold-dim}"
    textColor: "{colors.brand-gold}"
  button-primary-disabled:
    backgroundColor: "{colors.ink-well}"
    textColor: "{colors.text-tertiary}"
  button-line:
    backgroundColor: "transparent"
    textColor: "{colors.text-primary}"
    typography: "{typography.label}"
    rounded: "{rounded.edge}"
    padding: "8px 14px"
  button-refuse:
    backgroundColor: "transparent"
    textColor: "{colors.text-tertiary}"
    typography: "{typography.label}"
    rounded: "{rounded.edge}"
    padding: "8px 14px"
  panel:
    backgroundColor: "{colors.ink-panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.panel}"
    padding: "16px"
  input:
    backgroundColor: "{colors.ink-well}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.edge}"
    padding: "8px 10px"
  stamp-cleared:
    backgroundColor: "transparent"
    textColor: "{colors.channel-green}"
    typography: "{typography.label}"
    rounded: "{rounded.edge}"
    padding: "2px 7px"
  stamp-declared:
    backgroundColor: "transparent"
    textColor: "{colors.channel-red}"
    typography: "{typography.label}"
    rounded: "{rounded.edge}"
    padding: "2px 7px"
  stamp-refused:
    backgroundColor: "transparent"
    textColor: "{colors.channel-red}"
    typography: "{typography.label}"
    rounded: "{rounded.edge}"
    padding: "2px 7px"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.text-tertiary}"
    typography: "{typography.label}"
    rounded: "{rounded.edge}"
    padding: "4px 9px"
  chip-pressed:
    backgroundColor: "{colors.brand-gold-dim}"
    textColor: "{colors.brand-gold}"
  declaration-slip:
    backgroundColor: "{colors.stock}"
    textColor: "{colors.stock-ink}"
    rounded: "{rounded.edge}"
    padding: "14px 16px"
---

# Design System: Orchestra

## Overview

**Creative North Star: "The Border Post"**

Orchestra's job is to decide what crosses a boundary. Agents run on models you hold or on models
somebody else holds, and those are not the same kind of place. So the interface is not a dashboard
that reports on a boundary — it is the boundary. Work is inspected, stamped, and either cleared or
turned back, and every run ends with a document handed across the counter.

The surface is a night desk: an oxblood-ink ground, hairline rules, tracked mono caps on the form
fields, and a faint conic grain standing in for paper tooth. It is dark because the use scene is
dark — long sessions in a dim room beside a terminal and an editor. Warmth comes from the ink being
red-brown rather than blue-black, which is also what keeps it out of the near-black-plus-neon look
every agent tool ships.

One material breaks the ink, exactly once per run: a sheet of security paper carrying the
declaration. It is the only inverted surface in the product and the only place the stock colour
becomes a field rather than a detail. That scarcity is what makes it read as a document you were
handed rather than a panel that changed colour.

**Key Characteristics:**
- Warm near-black ground, not the category's blue-black
- Status carried by pressed rubber stamps and by position, never by hue alone
- Brand gold for identity; green and red reserved for channel state
- Tracked monospace caps for field names, system sans for everything readable
- Zero third-party requests: type is system stacks by product constraint

## Colors

A warm ink desk with two functional channels and one brand metal, kept in separate jobs so no
colour has to mean two things.

### Primary
- **Border Post Ink** (`#14100f`): The ground. A near-black carrying a deliberate red-brown cast, so
  the surface reads as a worn desk rather than a screen. Every panel sits on it.
- **Brand Gold** (`#d9c48c`): The wordmark, the mark artwork, and the focus ring. Identity only. It
  never indicates state, which is why it can sit permanently in the header without competing.

### Secondary
- **Green Channel** (`#56b47a`): Nothing to declare. Work that ran on a model you hold, the interior
  zone label, an open provider, a `cleared` stamp, a `green` row on the declaration.
- **Red Channel** (`#d75046`): Declared. Work that crossed to a hosted model, the border legend, the
  exterior zone, a `declared` or `refused` stamp, a `red` row. Red here means *declarable*, not
  *broken* — a customs red channel, not an error state.

### Tertiary
- **Amber Hold** (`#dda03a`): Waiting. A node queued behind a full lane, a dependency not yet met.
  The only colour that means "not yet".

### Neutral
- **Security Stock** (`#e9e2d5`): The declaration sheet, and nothing else. A material, not a tint —
  which is why it can only appear once.
- **Panel** (`#191413`) / **Raised** (`#1e1817`) / **Well** (`#241d1b`): Three ink steps for panel,
  nested surface, and input trough. Depth is tonal, not shadowed.
- **Rule** (`#352926`) and **Lit Rule** (`#4c3b36`): Hairline dividers; the lit variant marks the
  border itself and any hovered field.
- **Text** (`#f0e8dd` / `#bdb0a3` / `#8f8175`): Primary, secondary, chrome. All three clear AA on
  their own surfaces; the tertiary step is the floor and never carries body copy.
- **Slip inks** (`#5c5044` head, `#6b5f52` labels, `#ded6c7` footer band, `#2f7a4e` / `#a83228`
  channel marks): The declaration's own family. Stock is a light surface, so it needs its own dark
  text and its own darker channel values; the on-ink green and red would glare against it.

### Named Rules

**The Two Jobs Rule.** Gold means "this is Orchestra". Green and red mean "this is where the work
ran". A colour never does both jobs, which is why the brand can be permanent and the channel can be
loud.

**The One Sheet Rule.** Security stock is a field on exactly one element per run — the declaration.
Everywhere else it appears as a button fill or an active pill, never as a panel. If a second paper
surface appears on screen, the first one has stopped meaning anything.

**The Colour Is Not The Signal Rule.** Every state readable by colour is also readable without it:
a stamp with a word in it, a position above or below the border rule, a dotted versus solid border.
Test by rendering greyscale — no state may become ambiguous.

## Typography

**Display / Body Font:** system sans (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`)
**Label / Data Font:** system mono (`ui-monospace`, `SFMono-Regular`, `SF Mono`, `Menlo`)

**Character:** A form and its contents. Field names, stamps, buttons and navigation are tracked
monospace caps — the voice of a printed document's labelling. Everything a person actually reads is
system sans at a comfortable measure. There is no display face and no webfont, by product
constraint: a privacy-first tool that fetches type from a third party on load contradicts its own
claim.

### Hierarchy
- **Display** (700, 32px, 0.22em, uppercase, mono): The zone you are standing in — INTERIOR and
  EXTERIOR either side of the border band. The only type at this size, and the first thing the eye
  lands on in the hall.
- **Headline** (600, 20px, -0.01em): Desk titles. One per section, never stacked.
- **Title** (600, 15px): Panel headings.
- **Body** (400, 15px / 1.55): Transcript content, agent output, the answer.
- **Prose** (400, 13.5px, max 68ch): Explanatory copy under a heading. Always measure-capped.
- **Label** (600, 11px, 0.14em, uppercase, mono): Field names, stamps, buttons, nav, table headers.
- **Data** (400, 11px, 0.06em, mono, tabular): Model ids, provider routes, the machine-readable zone.

### Named Rules

**The Field-Name Rule.** Tracked uppercase is a *name*, not a sentence. A label is at most about
thirty characters; anything longer is sentence case in the note beneath the control. Long strings in
tracked caps wrap badly and read at half speed.

**The Eleven Pixel Floor.** No interactive or status text below 11px. Sub-11 is for nothing at all
in this system; the earlier 10px chip was a defect, not a tier.

**The Tabular Rule.** Any number that changes in place — elapsed seconds, byte counts, token counts,
the MRZ — uses tabular figures so it stops jittering as it updates.

## Layout

A single centred column at `max-width: 1160px` with 20px gutters, dropping to 14px under 720px.
Content is organised into panels: a 1px-ruled head strip carrying a title and status, over a 16px
body. Vertical rhythm inside a panel body is a flat 14px between children; panels themselves are
separated by 16px.

Rows are flex with 10px gaps and wrap by default; the growable member carries `min-width: 180px` so
a row collapses to stacked rather than crushing a control. Under 720px the header un-sticks into a
wrapping block, the nav becomes horizontally scrollable, agent bays go single-column, and the
composer's field takes full width so the action buttons sit beneath it rather than beside it.

The inspection hall is the one non-panel layout: a full-bleed grid of `minmax(268px, 1fr)` strips
separated by 1px rule-coloured gaps, so the bay reads as a sheet of adjacent slots rather than a row
of floating cards.

**The Gap Is The Divider Rule.** Inside the hall, separation comes from a 1px grid gap against a
rule-coloured background, not from borders on each strip. Strips are contiguous like slots in a rack.

## Elevation & Depth

Tonal, not shadowed. Depth is four steps of ink — ground, panel, raised, well — plus 1px rules.
Panels do not lift, do not glow, and do not blur what is behind them.

Two exceptions exist, both for things that genuinely float above the desk:

### Shadow Vocabulary
- **Lift** (`0 2px 4px rgba(0,0,0,0.4), 0 8px 24px rgba(0,0,0,0.32)`): The agent dialog. A modal is
  physically above the page.
- **Slip** (`0 3px 6px rgba(0,0,0,0.45), 0 18px 44px rgba(0,0,0,0.4)`): The declaration. A heavier,
  longer shadow because it is a sheet of paper resting on the desk, not a panel drawn in it.

### Named Rules

**The Flat Desk Rule.** Only two elements in the product cast a shadow: the dialog and the
declaration. Everything else earns its depth from tone. Adding a third shadow means the hierarchy
has stopped working and the fix is tonal, not a new shadow.

## Shapes

Almost square. `2px` on nearly everything — buttons, inputs, stamps, chips, chips, table cells — and
`3px` on panels, so a container reads as marginally softer than its contents. `50%` appears once, on
the 6px status tick.

Borders are the primary form device: 1px hairlines in `rule` for structure, `rule-lit` for the
border line and hover, and `1.5–2px` in `currentColor` for stamps, which is what makes a stamp read
as pressed rather than tinted. The `note-strip` uses a 3px double top border — a form's ruled-off
aside.

**The Barely-Round Rule.** Radius is 2px, not 8px. This is printed stationery, not an app card. If
something needs to feel softer, change its tone, not its corner.

**The Six Steps Rule.** The ramp is 11 / 12.5 / 13.5 / 15 / 20 / 32 and nothing else. Nine sizes
inside a ten-pixel band is not a hierarchy, it is drift; a new size means an existing role was
wrong.

## Components

### Buttons
- **Shape:** Barely rounded (2px), inline-flex with a 7px gap so an icon and label sit as one unit.
- **Primary:** Raised ink with a 1px gold rule and gold label (`#1e1817` / `#d9c48c`), 8px/14px
  padding, tracked mono caps at 11px.
- **Hover / Focus:** Primary fills to dim gold. Focus is a 2px gold outline at 2px offset,
  everywhere, without exception.
- **Line:** Transparent with a `rule-lit` border; hovers to a stock-coloured border on a raised fill.
- **Refuse:** Transparent with chrome-grey text and a lit rule at rest, reddening to the dim red fill
  on hover and focus. Destructive, but red is spent on the exterior channel, so it is not red until
  you reach for it.
- **Disabled:** Well-coloured fill, tertiary text, `not-allowed` cursor. Never merely faded.

### Stamps
The signature component. A status word inside a 1.5px `currentColor` border, rotated `-1.5deg`, and
on arrival animated once from `rotate(-9deg) scale(1.22)` to rest over 220ms on a
`cubic-bezier(0.16, 1, 0.3, 1)` — a press, not a fade. `refused` presses harder, from `-12deg`, and
rests at `-4deg` with a 2px border. `void` is dashed, for a thing that was never set up.

Variants: `cleared` (green), `declared` (red), `transit` (amber), `refused` (red, heavy), `void`
(tertiary, dashed).

### Cards / Panels
- **Corner:** 3px. **Background:** panel ink. **Border:** 1px rule. **Shadow:** none.
- **Head:** 11px/16px with a bottom rule, carrying a title, optional stamp, and a right-aligned
  status chip.
- **Internal padding:** 16px, with 14px between body children.

### Inputs / Fields
- Well-coloured trough, 1px rule border, 2px radius, 8px/10px padding.
- **Hover:** border lifts to `rule-lit`. **Focus:** 2px gold outline, offset 2px.
- **Disabled:** raised-ink fill with tertiary text.
- Selects are appearance-stripped with an inline chevron positioned 9px from the right; the native
  arrow is never relied on.

### Navigation
Tracked mono caps at 11px in tertiary. Hover lifts to primary text on a raised fill. The active item
takes a gold rule and gold label on ground ink. Sections
are hash-routed, so a desk is linkable and survives reload.

### Chips
Transparent with a `rule-lit` border and tertiary text; pressed takes dim-gold fill with a gold rule. Used for agent
selection and for the declarable-item toggles. `aria-pressed` carries the state, not just the class.

### The Border (signature component)
The mechanism made literal, and the reason this system exists. The inspection hall is split by a
ruled legend strip in red: interior above, exterior below. An agent strip is placed in the bay
matching where its model actually ran, and a step turned back by strict policy visibly moves from
the exterior bay to the interior one. A working strip carries a 2px inset rule on its leading edge,
green inside and red outside.

Both zones render from first load, before any run, with the mark at 132px and one sentence of
explanation. The border must read as a line *between two places*, never as a rule under the only
place there is.

### The Declaration (signature component)
The run's receipt, and the only inverted surface. Security stock on ink-dark text, `slip` shadow,
a ruled head carrying the verdict, a three-column table (route, channel, carried) with dotted row
rules, and a footer band in a darker stock carrying one plain-language sentence and a
machine-readable zone (`ORC<REDACT<LOCAL006<REMOTE000<HELD000<<<`). Channel cells are bordered
`decl` marks in the stock-appropriate green and red, never the on-ink channel values.

## Do's and Don'ts

### Do:
- **Do** state every status in a word inside a stamp, so the meaning survives greyscale and
  colour-blindness.
- **Do** keep gold for identity and green/red for channel. If a new state needs a colour, look for a
  position or a stamp first.
- **Do** cap explanatory copy at 68ch and put it in sentence case beneath the control it explains.
- **Do** animate `transform` and `opacity` only. The download gauge scales on X rather than
  animating width, because it updates continuously during a multi-gigabyte pull.
- **Do** honour `prefers-reduced-motion`: the stamp press and the live tick both stop, and nothing
  becomes ambiguous when they do.
- **Do** draw icons from the shared 16px sprite at 1.5px stroke with round caps and joins.
- **Do** give both border zones a label from first load, even when empty, and reserve each bay so
  the split exists before anything runs.
- **Do** render the border as the hatched band between double rules. It is the mechanism, not a
  caption; a label bar one tonal step from its panel is not a border.
- **Do** refuse destructive actions with a stamped dialog in the product's own voice, never a
  browser `confirm()`.
- **Do** paint a reading state before awaiting a round-trip. An empty container reads as "nothing
  here", which is a different and wrong claim.

### Don't:
- **Don't** add a shadow to anything that is not the dialog or the declaration. Depth is tonal here.
- **Don't** use security stock as a panel background. One sheet per run, or it stops meaning
  anything.
- **Don't** set a tracked-uppercase string longer than about thirty characters.
- **Don't** put interactive or status text below 11px.
- **Don't** introduce a webfont, an icon font, or any third-party asset request. The product's
  privacy claim is undermined by the page phoning anywhere on load.
- **Don't** rely on `hidden` alone for a component that sets its own display; the global
  `[hidden] { display: none !important }` exists because inline-flex buttons silently ignored it.
- **Don't** use red to mean "error" in the hall or on the declaration. Red is the declare channel;
  failure is a `refused` stamp with its own word, and a destructive button rests in `#8f8175`,
  reddening only on hover and focus.
- **Don't** spend security stock on chrome. Buttons, the active nav item, and pressed chips are
  gold-ruled ink; the moment cream becomes an ordinary button colour, the declaration stops being
  an event.
