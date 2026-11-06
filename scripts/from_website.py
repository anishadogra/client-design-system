#!/usr/bin/env python3
"""
from_website.py — draft a video design system from a website (a client's site, or a
brand whose feel you want to borrow). Reads the RENDERED page in headless
Chromium (computed styles, not guesses from raw CSS):

  palette     paper (largest background area), ink (most-used text colour), accent(s)
              (saturated colours on buttons / links / CSS variables)
  fonts       display (h1/h2), body (p), with weights; a local font file is linked only
              if one already exists locally (repo fonts/ or system fonts) — nothing
              is downloaded; @font-face sources are listed as an open question
  type scale  h1 / body size -> the nearest standard ratio (1.2 ... 1.618) and step count
  logo        candidates in the header (reported, not downloaded)

Writes a DRAFT (status "prospect") — it is a starting point to approve with
`ds.py sample <client>`, never a finished system. Refuses to overwrite an existing
system file; writes <client>.website-draft.json next to it instead.

Needs Playwright:  pip install playwright && playwright install chromium

    python3 scripts/from_website.py https://example.com --client newbrand [--shot site.png]
"""
from __future__ import annotations

import argparse
import colorsys
import datetime as dt
import json
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SYSTEMS = SKILL / "systems"
FONT_DIRS = [SKILL / "fonts",
             Path.home() / "Library" / "Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),  # macOS
             Path.home() / ".local" / "share" / "fonts", Path.home() / ".fonts", Path("/usr/share/fonts"),            # Linux
             Path("C:/Windows/Fonts")]                                                                                # Windows
STD_RATIOS = [(1.2, "minor third"), (1.25, "perfect fifth"), (1.333, "perfect fourth"),
              (1.414, "silver"), (1.618, "golden")]

JS = r"""
() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const info = e => { const cs = getComputedStyle(e); const r = e.getBoundingClientRect();
    return {tag: e.tagName, text: (e.innerText || '').trim().slice(0, 40), ff: cs.fontFamily, fw: cs.fontWeight,
            fs: parseFloat(cs.fontSize), color: cs.color, bg: cs.backgroundColor, area: r.width * r.height}; };
  const pick = sel => [...document.querySelectorAll(sel)].filter(vis).slice(0, 40).map(info);
  const roles = {h1: pick('h1'), h2: pick('h2'), h3: pick('h3'), p: pick('p'),
                 a: pick('a'), button: pick('button, .btn, [class*="button"], [class*="btn"]')};
  const bgs = {}, fgs = {};
  for (const e of document.querySelectorAll('body, body *')) {
    if (!vis(e)) continue;
    const cs = getComputedStyle(e); const r = e.getBoundingClientRect(); const a = Math.min(r.width * r.height, 4e6);
    if (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent')
      bgs[cs.backgroundColor] = (bgs[cs.backgroundColor] || 0) + a;
    const own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
    if (own) fgs[cs.color] = (fgs[cs.color] || 0) + own.length;
  }
  const vars = {}, faces = [];
  const root = getComputedStyle(document.documentElement);
  for (const s of document.styleSheets) {
    let rules; try { rules = s.cssRules; } catch (e) { continue; }
    for (const r of rules) {
      if (r.selectorText && /:root|html/.test(r.selectorText) && r.style)
        for (const n of r.style) if (n.startsWith('--')) vars[n] = root.getPropertyValue(n).trim();
      if (r.constructor && r.constructor.name === 'CSSFontFaceRule')
        faces.push({family: r.style.getPropertyValue('font-family'), weight: r.style.getPropertyValue('font-weight'),
                    src: r.style.getPropertyValue('src').slice(0, 240)});
    }
  }
  const logos = [...document.querySelectorAll('header img, header svg, a[href="/"] img, [class*="logo"] img, img[alt*="logo" i], [class*="logo"] svg')]
    .filter(vis).slice(0, 5).map(e => ({tag: e.tagName, src: e.currentSrc || e.src || null, alt: e.alt || null,
      w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height)}));
  return {title: document.title, url: location.href, roles, bgs, fgs, vars, faces, logos};
}
"""


def _hex(css: str) -> str | None:
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", css or "")
    if m:
        if m.group(4) is not None and float(m.group(4)) < 0.5:
            return None
        return "#{:02X}{:02X}{:02X}".format(*(int(float(m.group(i))) for i in (1, 2, 3)))
    m = re.match(r"#([0-9a-fA-F]{6})\b", (css or "").strip())
    return f"#{m.group(1).upper()}" if m else None


def _sat(h: str) -> float:
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    _, l, s = colorsys.rgb_to_hls(r, g, b)
    return s if 0.12 < l < 0.88 else 0.0


def _first_family(ff: str) -> str:
    return (ff or "").split(",")[0].strip().strip("'\"") or "unknown"


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(SKILL))
    except ValueError:
        return str(p)


def _local_font(family: str, weight: str | None) -> str | None:
    key = re.sub(r"\s+", "", family).lower()
    wt = {"700": "bold", "800": "extrabold", "900": "black", "600": "semibold"}.get(str(weight), "")
    best = None
    for d in FONT_DIRS:
        if not d.exists():
            continue
        for f in d.rglob("*.[ot]tf"):
            n = f.stem.replace("-", "").replace(" ", "").lower()
            if n.startswith(key):
                if wt and wt in n:
                    return _rel(f)
                best = best or _rel(f)
    return best


def _scale(h1: float | None, body: float | None) -> dict:
    if not h1 or not body or h1 <= body:
        return {"base_px_1080": None, "ratio": None, "notes": "could not measure h1/body"}
    best = None
    for k in (1, 2, 3, 4, 5):
        r = (h1 / body) ** (1 / k)
        for std, name in STD_RATIOS:
            err = abs(r - std) / std
            if best is None or err < best[0]:
                best = (err, std, name, k)
    err, std, name, k = best
    return {"base_px_1080": None, "ratio": std,
            "notes": f"measured on the site: h1 {h1:.0f}px / body {body:.0f}px = {std} ({name}) x {k} steps "
                     f"(fit error {err * 100:.1f}%). base_px_1080 for video is a decision for whoever approves the look."}


def extract(url: str, shot: str | None = None) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("[from_website] needs Playwright: pip install playwright && playwright install chromium")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(url, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(1200)
        data = pg.evaluate(JS)
        if shot:
            pg.screenshot(path=shot)
        b.close()
    return data


def draft(data: dict, client: str) -> dict:
    bgs = sorted(((h, a) for c, a in data["bgs"].items() if (h := _hex(c))), key=lambda x: -x[1])
    fgs = sorted(((h, n) for c, n in data["fgs"].items() if (h := _hex(c))), key=lambda x: -x[1])
    paper = bgs[0][0] if bgs else "#FFFFFF"
    ink = next((h for h, _ in fgs if h != paper), "#141414")
    cands: dict[str, float] = {}
    for el in data["roles"].get("button", []) + data["roles"].get("a", []):
        for c in (el["bg"], el["color"]):
            h = _hex(c)
            if h and _sat(h) > 0.25:
                cands[h] = cands.get(h, 0) + 1 + el["area"] / 1e5
    for n, v in data["vars"].items():
        h = _hex(v)
        if h and _sat(h) > 0.25:
            cands[h] = cands.get(h, 0) + (3 if re.search(r"primary|accent|brand", n, re.I) else 1)
    accents = [h for h, _ in sorted(cands.items(), key=lambda x: -x[1])][:3]
    palette = {"paper": paper, "ink": ink}
    for i, h in enumerate(accents):
        palette["accent" if i == 0 else f"accent_{i + 1}"] = h
    h1 = (data["roles"].get("h1") or data["roles"].get("h2") or [None])[0]
    ps = [e for e in (data["roles"].get("p") or []) if e.get("text")]
    if ps:  # the body size is the one most of the paragraph TEXT is set in, not the biggest box
        w: dict[float, int] = {}
        for e in ps:
            w[round(e["fs"])] = w.get(round(e["fs"]), 0) + len(e["text"])
        mode = max(w, key=w.get)
        body = next(e for e in ps if round(e["fs"]) == mode)
    else:
        body = {}
    disp_f, disp_w = (_first_family(h1["ff"]), h1["fw"]) if h1 else ("unknown", None)
    body_f, body_w = (_first_family(body.get("ff")), body.get("fw")) if body else ("unknown", None)
    fonts = {
        "display": {"family": disp_f, "weight": disp_w, "file": _local_font(disp_f, disp_w)},
        "body": {"family": body_f, "weight": body_w, "file": _local_font(body_f, body_w)},
    }
    fonts["caption"] = dict(fonts["display"], notes="captions default to the display face; confirm")
    oq = [f"DRAFT from {data['url']} — approve palette, fonts and caption look with `ds.py sample {client}` before use."]
    for role, f in fonts.items():
        if role != "caption" and not f["file"]:
            srcs = [x["src"] for x in data["faces"] if _first_family(x["family"]).lower() == f["family"].lower()][:2]
            oq.append(f"Font '{f['family']}' ({role}) is not installed locally — get the licensed file"
                      + (f"; the site loads it from: {srcs}" if srcs else ""))
    if data["logos"]:
        oq.append(f"Logo candidates on the site (not downloaded — use the client's REAL logo file, never a redraw): {data['logos'][:3]}")
    key = palette.get("accent", ink)
    return {
        "schema_version": "1.0", "client": client, "display_name": data.get("title") or client, "status": "prospect",
        "updated": dt.date.today().isoformat(), "inherits": "_house",
        "summary": f"Website-derived draft ({data['url']}). Not approved.",
        "palette": palette, "fonts": fonts,
        "type_scale": _scale(h1["fs"] if h1 else None, body.get("fs") if body else None),
        "captions": {
            "styles": {"brand": {"font": "caption", "fill": "#FFFFFF",   # white + ink stroke reads on any footage
                                 "stroke": "ink", "stroke_px": 6, "keyword_fill": key,
                                 "shadow": {"color": "#000000", "opacity": 0.35, "dx": 0, "dy": 3, "blur": 6}}},
            "style_cycle": ["brand"], "tilt_deg": [0, 0],
            "notes": "One uniform style until a ruling says otherwise; placement inherits the house rules."},
        "references": {"website": data["url"], "approved_builds": [], "reference_reels": []},
        "open_questions": oq,
        "sources": [f"website:{data['url']} (computed styles, {dt.date.today().isoformat()})"],
        "_extracted": {"css_vars": dict(list(data["vars"].items())[:40]), "font_faces": data["faces"][:10],
                       "backgrounds": bgs[:6], "text_colours": fgs[:6], "logos": data["logos"]},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--client", required=True)
    ap.add_argument("--shot")
    ap.add_argument("--out")
    a = ap.parse_args()
    data = extract(a.url, a.shot)
    d = draft(data, a.client.lower())
    out = Path(a.out) if a.out else SYSTEMS / f"{a.client.lower()}.json"
    if out.exists():
        out = out.with_name(f"{a.client.lower()}.website-draft.json")
    out.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print(out)
    print(json.dumps({"palette": d["palette"], "fonts": {k: (v["family"], v["weight"], bool(v["file"])) for k, v in d["fonts"].items()},
                      "type_scale": d["type_scale"]}, indent=1))


if __name__ == "__main__":
    main()
