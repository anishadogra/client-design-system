# Client Design System

One JSON file per client that holds everything a short-form video needs to look like that client: palette, fonts, type scale, caption styles and the order they cycle in, caption placement for each aspect ratio, safe zones, logo rules, motion and audio rules, the client's sacred rules quoted word for word, and the questions nobody has answered yet. Every video job reads it first. A house file holds the defaults; each client file is deep-merged on top, and every value points back to where it came from. It can also draft a new system from a website and render a sample sheet to approve before anything is cut.

By Anisha Dogra, co-founder of [RAAY Creative](https://raaycreative.com). This came out of a studio where the style rules for each client lived in five places at once (old briefs, a long lessons file, past build scripts, chat history and one person's memory) and every new edit quietly picked a different one. Corrections and disagreements are welcome — [open an issue](../../issues/new) before opening a pull request.

## The problem

A client's look is not one decision. It is forty small ones: which yellow, how big the captions are, whether they sit above the head or at the chest, how far from the hairline, whether they tilt, which word gets the colour, where the logo goes on a landscape cut, how loud the music sits under speech. Each one was settled once, on some job, usually after a correction.

Then the next job starts from a blank file. The editor, or the agent, remembers most of the rules. It re-derives a few. It guesses the rest, and the guesses look plausible, so nobody notices until the client does. The same correction gets made a second time, then a third.

The second problem is quieter. When a rule exists in three places, the three copies drift. One says captions centre at x480, another says x540, and both cite a job as their source. An agent that finds one of them will apply it with full confidence.

So the rules go in one file per client, with a source for every value, and anything unsettled is written down as a question instead of being answered by whoever touches the file next.

## The rules that matter most

**Never invent a value.** Every colour, size, path and rule comes from a source listed in `sources`: a brief, a brand guide, a dated ruling, a reference build. If it is not known, it is `null` and it goes into `open_questions`. A plausible guess in a design system is worse than a gap, because it looks settled.

**Open questions are asked, not answered.** `ds.py rules <client>` prints them under "OPEN — ask, never assume". They exist so the agent stops and asks instead of filling the hole with its own taste.

**Sacred rules are quoted verbatim.** If a client said it in a particular way, the file keeps it that way. Paraphrase is how a hard rule turns into a suggestion.

**Captions never drift.** One solved size, one line, a fixed y for the cut, baseline-anchored tiles. The caption engine measures INK (glyphs plus stroke, after rotation), not the layer box, because placement by layer box is how text ends up under the like button.

## What is in here

| | |
|---|---|
| **[schema/design-system.schema.json](schema/design-system.schema.json)** | The contract for a system file. Read it before editing one. |
| **[systems/_house.json](systems/_house.json)** | House defaults every client inherits: measured Instagram safe zones (text floor y290, nothing readable below y1520, nothing right of x900), caption placement modes, no-drift rules, logo rule, motion timings, the audio chain. |
| **[systems/example-snack-brand.json](systems/example-snack-brand.json)** | A fictional client with a full file: five-style caption cycle with tilt, keyword chips, product-name label rules, sacred rules. |
| **[systems/example-creator.json](systems/example-creator.json)** | A fictional creator page with a minimal file that leans on the house defaults, including a 16:9 caption column. |
| **[scripts/ds.py](scripts/ds.py)** | Load, merge, print rules, validate, and render a sample sheet. |
| **[scripts/captions.py](scripts/captions.py)** | The caption type engine: draws one caption card in a client's style and reports its ink box. |
| **[scripts/from_website.py](scripts/from_website.py)** | Drafts a system (status `prospect`) from a website's rendered styles: palette, fonts, type-scale ratio, logo candidates. |
| **[SKILL.md](SKILL.md)** | The whole thing as a drop-in agent skill. |

## How to use it

Needs Python 3.9+ and Pillow. `jsonschema` is optional (validation uses it when installed). `from_website.py` needs Playwright.

```bash
pip install pillow jsonschema
python3 scripts/ds.py list
python3 scripts/ds.py rules example-snack-brand     # brief-ready text: sacred rules, captions, open questions
python3 scripts/ds.py show example-snack-brand      # merged JSON (house <- client)
python3 scripts/ds.py validate                      # schema, fonts and logos exist, style refs resolve
python3 scripts/ds.py sample example-snack-brand --out look.png --frame still.jpg
```

Fonts are not in the repo. Inter, Poppins and Anton are free on [Google Fonts](https://fonts.google.com); put the `.ttf` files listed in [fonts/README.md](fonts/README.md) into `fonts/`. If a font a system names is missing, the scripts stop and say which file.

To add a client, copy one of the example files to `systems/<client>.json`, fill in only what you have a source for, list the source, and put everything else in `open_questions`. Run `ds.py validate`, then `ds.py sample` and get the sheet approved before the first render.

To start from a website:

```bash
pip install playwright && playwright install chromium
python3 scripts/from_website.py https://brand.com --client newbrand
```

It reads computed styles from the rendered page, not raw CSS. It never overwrites an existing file and never downloads fonts or logos; the logo is always the client's real file.

From Python, inside a renderer:

```python
import sys; sys.path.insert(0, "scripts")
import ds
d = ds.load("example-snack-brand")
ds.placement(d, "9:16"); ds.safe_zone(d, "9:16"); ds.caption_styles(d)
```

Merge rule: dictionaries merge key by key; a list or a scalar in the client file replaces the house value, so a client can shorten a style cycle without inheriting the house one.

## A note on the house file

The numbers in `_house.json` were measured, not looked up: the safe zones against real Instagram chrome on 1080x1920 frames, the caption gap against approved reels, the music level against what clients accepted and rejected. Some of them will be wrong for your work. Change them in your fork, and keep the habit of writing down where each new number came from.
