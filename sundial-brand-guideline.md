# Sundial: Brand Guideline

**Version 1.1 · November 2026**
**Status:** Draft for review. Items marked **[DECIDE]** are open choices. See Section 14.

---

## How to read this document

Every section has two parts: the rule, and the reason behind it. If you disagree with a rule, check the reason first. If the reason no longer holds, change the rule.

This guideline is built from the engine README. Every claim about the product comes from it. Nothing here should promise more than the engine can prove.

---

## 1. The brand in one page

**Name:** Sundial
**Category:** University timetabling software
**Core idea:** Time, worked out.

**Promise:** A timetable with no clashes, and a clear reason for every placement.

**Why this works:** A sundial is the oldest honest clock. It has no battery, no hidden parts and no guesswork. One fixed pin (the gnomon) throws one shadow, and you can see exactly why it reads the time it reads. That is the engine: built from first principles, no black-box solver, zero backtracks, fully traceable.

### Personality

| We are | We are not |
| :--- | :--- |
| Precise | Fussy |
| Calm | Slow or sleepy |
| Plainspoken | Jargon-heavy |
| Transparent | Mysterious or "magic" |
| Sturdy and built to last | Trendy or gimmicky |
| Understated | Cute or clever for its own sake |
| Confident from proof | Loud or hyped |

### What we never say

- **Never "AI-powered".** The engine is a deterministic constraint solver. It follows rules and shows its work. Calling it AI would hide our best feature.
- **Never "smart" or "magic".** Say what it does instead.
- **Never claim more than the benchmark shows.** See Section 3.
- **No puns, slang or cute language in the product.** Plain beats clever.

---

## 2. Audience

Ranked by who decides, then who uses.

| Audience | What they care about | What we show them |
| :--- | :--- | :--- |
| **Registrars and timetable officers** | No clashes. Less manual work. No angry lecturers. | Clash count. Time saved. A timetable they can defend. |
| **Deans and heads of department** | Their labs and workshops used properly. Fewer Saturday classes. | Venue affinity. Saturday numbers. |
| **IT directors** | Can we plug it in? Can we trust it? | JSON config. Open logic. No black box. |
| **Lecturers and students** | A timetable that makes sense. | Clean output. Clear print. |
| **Developers (inside the uni or partners)** | Readable docs. Predictable behaviour. | Plain technical writing. Real examples. |

**Why this order:** A registrar signs the deal. A lecturer judges it every week on the wall. Both must feel the brand is on their side.

---

## 3. Positioning and proof

### Positioning statement

For university timetable teams who are tired of clashes and manual rework, Sundial is a timetabling engine that builds a clash-free schedule in about a second and can explain every placement. Unlike black-box schedulers, it is built from first principles and every rule is visible.

### Proof points (from the README)

Use these. Always include the source line.

| Claim | Number | Source line to print with it |
| :--- | :--- | :--- |
| Clashes in generated timetables | **0** | "ATC benchmark, 1,233 sessions" |
| Clashes in the original human timetable | **81 pairs** | "ATC master timetable, 1,299 sessions" |
| Solve time | **under 1.2 seconds** | "ATC benchmark, Modes A and B" |
| Backtracks | **0** | "ATC benchmark" |
| Specialised labs and workshops kept in their own department | **100%** | "306 of 306 sessions, Mode A" |
| Cohorts with no Saturday classes | **111 of 121 (91.7%)** vs 86 of 121 (71.1%) by hand | "ATC benchmark, Mode A" |

### Proof rules

1. **Name the dataset every time.** "ATC benchmark" is the minimum.
2. **Do not generalise.** "Zero clashes on ATC data" is true. "Zero clashes at any university" is not yet proven.
3. **Say "generated" or "hand-built", not "good" or "bad".** The numbers do the judging.
4. **Mode A and Mode B are different.** Do not mix their numbers in one sentence.
5. **Update these numbers when the engine changes.** Old proof is a liability.

### Key messages

1. **No clashes.** Lecturers, cohorts and venues are never double-booked.
2. **Fast.** About a second for a full institution.
3. **Traceable.** Every placement follows a visible rule.
4. **Fits your campus.** Rules live in a JSON config. Your calendar, your venues, your streams.
5. **Respects your labs.** A workshop stays in its own department.
6. **Kinder to students.** Saturday classes only when the numbers force them.

---

## 4. Name and naming system

### Why "Sundial"

- It matches the idea: a simple, visible way of telling time.
- It matches the README's own artwork, which already uses a dial.
- It is short and easy to say and spell in any language.

### Naming system

| Name | What it is | Where it appears |
| :--- | :--- | :--- |
| **Sundial** | The product (the web app) | Everywhere customers look |
| **Sundial Engine** | The solver core | Docs, technical pages |
| **Sundial Viewer** | The timetable visualiser and PDF renderer | App, docs |
| **Sundial Schema** | The JSON config format (`institution_schema.json`) | Developer docs |
| `sundial-engine` | The repository and package | Code only |

**Rules**

- Write **Sundial** with a capital S in prose.
- Write `sundial-engine` in code font, only when you mean the repo or package.
- Do not add suffixes like "Pro", "Plus" or "AI".

### Name check

Sundial is a common word. Before the logo is finalised, search trademark registers and domain names in the markets you plan to sell in. If the name is taken, pick a different name or add a distinguishing word.

### Tagline

Primary: **Time, worked out.**

It has two meanings: the time is scheduled, and the maths is shown. See Section 14 for alternatives.

Supporting lines (use one at a time):

- "Zero clashes. Every decision traceable."
- "Built from first principles."
- "Timetabling for universities."

---

## 5. Voice and tone

### Principles

1. **Short sentences.** One idea each.
2. **Plain words.** Say "clash", not "constraint violation".
3. **Show, don't hype.** A number beats an adjective.
4. **Say why.** If the engine placed something, say the reason.
5. **Be calm when things go wrong.** Say what happened and what to do next.

### Do and don't

| Do | Don't |
| :--- | :--- |
| "No clashes found." | "Congratulations! Your schedule is perfectly optimised!" |
| "Dr Rao is booked in two rooms on Monday, P3." | "A resource conflict was detected." |
| "This session is on Saturday because the cohort has 64 periods. Monday to Friday holds 60." | "Saturday was selected by our intelligent algorithm." |
| "Upload your venues." | "Leverage your venue data to unlock insights." |
| "Solved in 0.9 seconds." | "Lightning-fast results." |

### Words we use

Spelling is **British English** as a house style (timetable, programme, venue, centre). Keep it consistent across all copy.

| Use | Avoid | Note |
| :--- | :--- | :--- |
| clash | conflict (in app copy) | "Conflict" is fine in technical docs. "Clash" is shorter and plainer. |
| session | event, class slot | One weekly teaching block. |
| lecturer | instructor, professor | Matches ATC data. |
| venue | resource, location | Rooms, labs, workshops, field sites. |
| cohort | student group | Matches the data model. Explain once on first use. |
| stream | track, shift | Full-Time and Evening. |
| period | slot | One 45-minute block. |
| programme | program | British spelling. |
| rule | constraint (in app copy) | Use "constraint" in docs for developers. |
| placed | assigned, allocated | |

### Plain words for the technical ideas

Marketing and onboarding should explain the engine without the jargon.

| Technical term | Plain version |
| :--- | :--- |
| Constraint satisfaction | Checking every rule before placing anything |
| Hard constraint | A rule that can never be broken |
| Soft constraint | A preference we try to meet |
| Backtracking | Undoing a choice and trying another |
| Pigeonhole check | A check that there is enough time and space before we start |
| Conflict graph | A map of who and what cannot overlap |

### Example copy

**Hero line:** Time, worked out.
**Sub line:** Sundial builds a clash-free university timetable in about a second. Every placement follows a rule you can read.

**Success message:** Timetable ready. 1,233 sessions placed. 0 clashes. 17 on Saturday.

**Warning:** 3 cohorts have more than 60 periods a week. Their extra sessions will move to Saturday.

**Error:** We could not place 2 sessions. The Electrical Lab has no free periods for them. Add a venue or change the sessions.

**Empty state:** No venues yet. Add your first venue to start.

---

## 6. Logo

> This section describes the logo. The mark still needs to be drawn. Section 14 lists the directions to choose from.

### Parts

1. **Symbol:** a dial with a gnomon and a shadow.
2. **Wordmark:** "sundial" in lowercase, in the brand typeface.
3. **Lockup:** symbol and wordmark together.

### Symbol directions

| Option | Idea | Strength | Risk |
| :--- | :--- | :--- | :--- |
| **A. The dial** | A circle with a vertical gnomon and a shadow wedge falling across it | Closest to the README art. Works as a favicon and app icon. | Common sundial imagery. Needs a sharp, original execution. |
| **B. The shadow grid** | A 6-column grid (the six days) with one diagonal shadow cutting across it | Ties directly to the timetable and the 108-slot grid. | Can look like a generic table icon. |
| **C. The "i" gnomon** | The lowercase "i" in the wordmark. Its dot is the sun. Its stem is the gnomon. | Wordmark-only, simple, ownable. | Weak as a standalone icon. Leans clever, which the brand should avoid. |

**Recommendation: A, kept heavy and plain.** The circle gives a strong app icon. A thick gnomon and a hard-edged shadow make it feel sturdy, not decorative. The wordmark stays plain lowercase with no special letter treatments. This is a suggestion. Section 14 asks you to choose.

### Construction notes (for Illustrator)

- Build on a square artboard with a circle that touches the edges.
- The gnomon is one vertical bar, centred. Keep its edges straight. No rounded top.
- The shadow is a single wedge at a fixed angle. Use **one angle across all brand uses**. Suggested start: 30 degrees. Test 30 and 45 at small sizes.
- Use at most **two colours** in the symbol: Shadow and Noon (Section 7).
- Keep the stroke weight even and heavy. No thin lines. At 16 px it must still read.

### Lockups

- **Horizontal:** symbol left, wordmark right. The default.
- **Stacked:** symbol above wordmark. For square spaces.
- **Symbol only:** favicon, app icon, social avatar.

### Clear space

Leave space around the logo equal to **the width of the gnomon bar, times three**. If you have not drawn the mark yet, use half the height of the symbol until you do.

### Minimum size

- Symbol only: 16 px on screen, 6 mm in print.
- Horizontal lockup: 96 px wide on screen, 25 mm in print.

### Colour versions

1. Full colour on Stone or white.
2. Stone and Noon on Shadow (dark backgrounds).
3. One-colour Shadow (print, stamps, fax and photocopy).
4. One-colour white (on photos and dark colours).

### Misuse

Do not:

- Change the shadow angle.
- Stretch, rotate or skew the logo.
- Add glows, gradients or drop shadows.
- Put the full-colour logo on Noon or Indigo. Use a one-colour version.
- Replace the wordmark font.
- Add a university logo inside the Sundial logo. Use the partner lockup (Section 10).

---

## 7. Colour

### Idea

Two colours carry the brand. **Indigo** is a deep, steady blue. It reads as serious and dependable. **Noon** is a warm amber, used in small amounts as the sun. They sit opposite each other on the colour wheel, so they stand apart without effort.

This also matches the data. The system has two streams: **Full-Time** (daylight, P1 to P12) and **Evening** (P13 to P18). The brand colours map straight onto them.

### Palette

| Name | Hex | Role |
| :--- | :--- | :--- |
| **Shadow** | `#11151C` | Primary text. Dark backgrounds. The gnomon. |
| **Stone** | `#F4F1EA` | Main background. Warm, like sundial limestone. |
| **Indigo** | `#1F2A6B` | Primary brand colour. Buttons, links, headings, Evening stream. |
| **Noon** | `#F2A71B` | Accent. The sun. Highlights, Full-Time stream. Never for text on light backgrounds. |
| **Slate** | `#5A6272` | Secondary text. |
| **Dust** | `#D9D4C7` | Lines, borders, dividers. |
| **Dusk** | `#E3E6F5` | Light Indigo tint. Evening stream backgrounds. |
| **Daybreak** | `#FBE8B8` | Light Noon tint. Full-Time stream backgrounds. [DECIDE: confirm after testing on screen and print] |

### Status colours

These carry meaning. Do not use them for decoration.

| Name | Hex | Use |
| :--- | :--- | :--- |
| **Clear** | `#26704F` | No clashes. Success. |
| **Clash** | `#C0392B` | A hard rule is broken. Errors. |
| **Caution** | `#8A5A00` | A warning, like a Saturday placement. Use as text. Use Noon as a fill with Shadow text. |

### Usage balance

Roughly:

- **60%** Stone (and white)
- **25%** Shadow and Slate
- **10%** Indigo
- **5%** Noon

Noon is small on purpose. It should feel like a point of sunlight.

### Contrast (approximate, verify before shipping)

| Pair | Ratio | Result |
| :--- | :--- | :--- |
| Shadow on Stone | about 16:1 | Passes AAA |
| Indigo on Stone | about 11:1 | Passes AAA |
| Slate on Stone | about 5.4:1 | Passes AA |
| Clash on Stone | about 4.8:1 | Passes AA |
| Clear on Stone | about 5.3:1 | Passes AA |
| Noon on Shadow | about 9:1 | Passes AAA |
| **Noon on Stone** | **about 1.8:1** | **Fails. Never use for text.** |

I worked these out by hand. Run them through a contrast checker before anything ships.

### Rules

1. **Never use colour alone to show meaning.** Pair it with a label, icon or pattern. This helps colour-blind users and photocopies.
2. **Noon is never body text on a light background.**
3. **Status colours are fixed.** Partner universities cannot change them (Section 10).
4. **Dark mode:** Shadow background, Stone text, Noon and a lightened Indigo for accents.

### Stream colours in timetables

| Stream | Fill | Text | Print pattern |
| :--- | :--- | :--- | :--- |
| Full-Time | Daybreak | Shadow | Solid |
| Evening | Dusk | Shadow | Fine diagonal hatch |
| Saturday sessions | Same stream fill | Shadow | Small "Sat" tag |

The print pattern means a black-and-white photocopy still tells the streams apart.

---

## 8. Typography

### Choice

| Role | Typeface | Why |
| :--- | :--- | :--- |
| **Headings and body** | **IBM Plex Sans** | Clear, neutral, built for dense information. Free. Wide Latin-script language coverage. |
| **Data and code** | **IBM Plex Mono** | Session IDs (`S0001`), module codes, times, config. Same family, so it sits well with the sans. |

Both are open source and available on Google Fonts. No licence cost for universities.

**Why a mono for data:** Timetable data is full of codes and times. Equal-width characters line up in columns and are easier to scan and compare.

**Fallback stack:** `"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`

### Type scale

| Use | Size | Weight |
| :--- | :--- | :--- |
| Display | 40 to 56 px | Semibold (600) |
| H1 | 32 px | Semibold |
| H2 | 24 px | Semibold |
| H3 | 18 px | Medium (500) |
| Body | 16 px | Regular (400) |
| Small / table | 14 px | Regular |
| Caption | 12 px | Regular |
| Code and data | 14 px | Plex Mono Regular |

### Rules

- **Use tabular numerals** wherever numbers line up in a column.
- Line length: 60 to 75 characters for reading text.
- Line height: 1.5 for body, 1.2 for headings.
- Sentence case for headings. Not Title Case, not ALL CAPS.
- Do not go below 12 px, and never below 10 pt in print.

---

## 9. Graphic language

### The grid

The brand's main visual idea is the **weekly grid**: 6 days by 18 periods, 108 slots. It is the real shape of the product, so it becomes the brand's texture.

Uses:

- Faint grid lines as a background pattern on covers and headers.
- One cell filled in Noon, to mean "placed".
- Empty cells left empty. Empty space is part of the story.

### The shadow line

A single diagonal line at the brand's shadow angle. Use it as a divider, a crop on images, or the edge of a coloured panel. Use it sparingly. One per layout.

### Iconography

- Line icons, 1.5 px stroke at 24 px, square or slightly rounded caps.
- Draw from timetable ideas: clock, grid, room, lecturer, cohort, clash, venue pin.
- One icon style across the whole product. Do not mix filled and outline sets.

### Photography and illustration

- Real campuses, real people, real light. Shot in natural daylight, no staging.
- No stock photos of white-collar teams around laptops.
- No robots, circuit brains, glowing networks or purple gradients. They say "AI", and we are not selling AI.
- Illustration (if used): flat shapes, the brand palette, grid and shadow motifs.

### Data display

- Show the **clash count** first and make it big. "0 clashes" is the headline.
- Show numbers with units and source ("1,233 sessions · ATC benchmark").
- Use Plex Mono for IDs, codes and times.
- Never hide a clash. If there is one, it shows in Clash red with a label and a link to the cause.

### Motion (for later UI work)

- Short and purposeful. 150 to 250 ms.
- Motion should be steady and plain. No bounce, no flourishes.
- Respect "reduce motion" settings.

---

## 10. Partner and white-label rules

Each university will integrate Sundial into its own systems. Their brand matters more than ours on anything their people see.

### Principle: **Their name outside, Sundial inside.**

| Surface | Whose brand leads |
| :--- | :--- |
| Timetable PDFs and printouts | The university (logo, name, colours) |
| Embedded views inside a uni portal | The university |
| Admin app (timetable officers) | Sundial, with the uni name and logo in the header |
| API, docs and config | Sundial |
| Emails to staff | The university, with a footer line |

### Footer credit

Small line on partner output: **"Scheduled with Sundial"** with the symbol only.

### What a university can change

- Logo
- Name
- One accent colour (must pass contrast on Stone and on Shadow)
- Header and footer text

### What a university cannot change

- Status colours (Clear, Clash, Caution)
- Stream pattern logic (hatch for Evening)
- The clash count display
- The footer credit, unless a licence says so

**Why:** Status colours must mean the same thing everywhere. A red clash should never look like decoration.

### For integrators

Treat brand settings as config, like the rest of the system. Suggested `brand` block in the institution schema:

```json
{
  "brand": {
    "institutionName": "Example University",
    "logo": "assets/logo.svg",
    "accentColor": "#7A1F2B",
    "showSundialCredit": true
  }
}
```

The engine already reads declarative JSON. Brand settings belong in the same place.

---

## 11. Print and PDF

The README mentions an **A4 landscape PDF renderer**. Printed timetables are the most-seen part of the product. They get pinned to walls, photocopied and photographed on phones.

### Rules

1. **Design for black and white first.** Add colour second.
2. **Use patterns and labels, not colour alone**, for streams and statuses.
3. **Minimum text size: 8 pt** in dense grids. Prefer 9 pt.
4. **Header block:** university logo, programme, level, cohort, academic period.
5. **Footer block:** generation date, version, "Scheduled with Sundial", and a short code so staff can check the print is current.
6. **Show clashes clearly** if a draft has any. Never print a draft that looks final.
7. **Plain, short module names with the code in Plex Mono.**

**Why:** A timetable on a wall gets old fast. A date and version stop people following a stale schedule.

---

## 12. Accessibility and language

- Target **WCAG 2.2 AA** at minimum.
- All meaning has a text or icon backup, not colour alone.
- Keyboard-usable everywhere in the app.
- Touch targets at least 44 px.
- Plain reading level. Aim for something a first-year student reads without effort.
- **Translation ready.** Build the app so every string can be translated. Keep sentences short and avoid idioms, which makes translation easier.
- Allow for translated text being longer than English in buttons and labels.
- Use 24-hour or 12-hour time to match the institution's setting. ATC periods run `07:30` to `22:40`. Keep the format configurable.

---

## 13. Quick do and don't

**Do**

- Lead with the clash count.
- Name the dataset next to every number.
- Use plain words.
- Let the university's brand lead on their output.
- Keep Noon small.

**Don't**

- Say "AI", "smart" or "magic".
- Use puns, slang or cute language in the product.
- Put Noon text on a light background.
- Use colour alone to show meaning.
- Claim results beyond the benchmark.
- Mix status colours into decoration.

---

## 14. Open decisions

These are the choices that shape everything else. Each has a recommendation, but they are yours to make.

### 14.1 Tagline

| Option | Line | Feel |
| :--- | :--- | :--- |
| **A (recommended)** | Time, worked out. | Double meaning: scheduled and calculated. Light wordplay only. |
| B | Every hour, placed. | Clear and literal. Less memorable. |
| C | Zero clashes. Fully traceable. | Pure proof. Better as a supporting line than a tagline. |
| D | Timetabling that shows its work. | The plainest option. Says the main difference directly. Pick this if you want zero wordplay. |

### 14.2 Logo direction

A (the dial), B (the shadow grid), or C (the "i" gnomon). See Section 6. Recommended: A, kept heavy and plain.

### 14.3 Primary typeface

| Option | Pair | Feel |
| :--- | :--- | :--- |
| **A (recommended)** | IBM Plex Sans + Plex Mono | Engineered, neutral, one family |
| B | Inter + JetBrains Mono | Familiar, very readable. Very common. |
| C | Manrope + IBM Plex Mono | Slightly warmer, more rounded |

### 14.4 Name check

Confirm "Sundial" is free to use in the markets you plan to sell in (trademark registers and domains). If it is not, pick a different name or add a distinguishing word.

---

## 15. Before launch checklist

- [ ] Choose the tagline, logo direction and typeface (Section 14)
- [ ] Draw the symbol and test it at 16 px
- [ ] Run all colour pairs through a contrast checker
- [ ] Test the stream hatch on a real black-and-white photocopy
- [ ] Trademark and domain check
- [ ] Confirm every proof point with a fresh engine run
- [ ] Add the `brand` block to the institution schema
- [ ] Build one sample partner timetable (ATC) to test the white-label rules

---

## Appendix: Design tokens (starter)

```css
:root {
  /* Colour */
  --shadow: #11151C;
  --stone: #F4F1EA;
  --indigo: #1F2A6B;
  --noon: #F2A71B;
  --slate: #5A6272;
  --dust: #D9D4C7;
  --dusk: #E3E6F5;
  --daybreak: #FBE8B8;

  /* Status */
  --clear: #26704F;
  --clash: #C0392B;
  --caution: #8A5A00;

  /* Type */
  --font-sans: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;

  /* Shape */
  --radius: 6px;
  --shadow-angle: 30deg;
}
```
