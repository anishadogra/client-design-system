---
name: client-design-system
description: >-
  One VIDEO DESIGN SYSTEM file per client that every video job reads FIRST: palette,
  fonts, type scale, caption styles + style cycle + tilt, caption placement per aspect
  (9:16 / 16:9 / 1:1 / 4:5), safe zones, logo files + placement, motion and audio rules,
  sacred rules quoted verbatim, approved formats, and OPEN questions that must be asked,
  never assumed. House defaults are deep-merged with the client file, and every value is
  traceable to a source. Also drafts a system from a website and renders a visual sample
  sheet for approval. Use when starting any video job for a client ("load the snack
  brand's style", "what are this client's caption rules"), when a new client needs a look
  ("make a design system from this website"), when someone wants to see or approve the
  look ("show me the caption styles"), and in every debrief that settles a style ruling
  (write it into the file).
---

# Client design system

```
schema/design-system.schema.json   the contract (read it before editing a file)
systems/_house.json                house-wide rules every client inherits
systems/<client>.json              one file per client
fonts/                             caption and display faces (not committed; see fonts/README.md)
scripts/ds.py                      list / show / rules / validate / sample
scripts/captions.py                the caption type engine
scripts/from_website.py            website -> DRAFT design system
```

## Use it

```bash
python3 scripts/ds.py list
python3 scripts/ds.py rules <client>      # paste into the job brief: sacred rules, captions, OPEN questions
python3 scripts/ds.py show <client>       # merged JSON (house <- client)
python3 scripts/ds.py validate            # schema, fonts/logos exist, style refs resolve
python3 scripts/ds.py sample <client> --out look.png --frame still.jpg   # the approval sheet
python3 scripts/from_website.py https://brand.com --client newbrand      # DRAFT from a site
```

In Python: `sys.path.insert(0, "<repo>/scripts"); import ds; d = ds.load("<client>")`. Merge rule: dicts
merge key by key; a list or scalar in the client file replaces the house value.

## Rules for editing a system file
- **Never invent a value.** Every colour, size, path and rule comes from a source listed in `sources`
  (brief, brand guide, dated ruling, reference build). Unknown -> `null` + an `open_questions` entry.
- `sacred_rules` are quoted verbatim, never paraphrased.
- Two rulings that both hold for different frames (above-head vs chest/elbow captions) are expressed as
  `captions.placement[aspect].mode` + `fallback`, with a note, not by picking one.
- `open_questions` are asked, never answered by assumption.
- **Debrief duty:** when a job settles a style ruling, write it into the client's file, add the source,
  bump `updated`, and run `ds.py validate`.
- A website draft is status `prospect` until its sample sheet is approved. `from_website.py` never
  overwrites an existing system (it writes `<client>.website-draft.json` instead) and never downloads
  fonts or logos. Logos are the client's REAL files, never a redraw.

## Who reads it
- Footage prep: prints `ds.py rules <client>` into the job notes before planning.
- The renderer: canvas, safe zones, caption styles, cycle and placement per aspect, logo.
