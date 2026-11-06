#!/usr/bin/env python3
"""
captions.py — the caption type engine. Draws one caption card in a client's style
(from the design system) and reports its INK bounding box, so placement code can
anchor by ink (text + stroke + plates), never by the layer box.

Craft rules baked in (each one learned on a real job; do not "simplify" them away):
  * plates are drawn PER LINE, never one box round the block (a block box reads
    as a subtitle bar);
  * width is fitted on INK with the stroke included (stroke widens every line);
  * tilt is applied to the whole card and the ink box is re-measured AFTER the
    rotation — placement uses the rotated ink box;
  * the shadow is excluded from the ink box (it is a soft halo, not the edge).

Pure PIL. Used by ds.py sample and by any renderer that wants the same type engine.

    python3 scripts/captions.py example-snack-brand out.png    # render one test caption
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

STOPWORDS = set("""
a an the is are was were be been am i you he she it we they me my your our their this that these those
to of and or in on at for with from by as so but if then than just very really also not no yes do does did
have has had will would can could should like okay ok um uh hmm yeah oh hey hi
hai hain tha thi the ka ki ke ko se me mein main mai toh to ye yeh wo woh aur bhi na nahi nahin ek kya kyu
kyun kaise jo ab par pe ho hota hoti hote raha rahi rahe gaya gayi karo kar karna karke apna apni apne
""".split())


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, int(size))
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(path, int(size))
    return _FONT_CACHE[key]


def _rgba(hexv: str | None, alpha: float = 1.0) -> tuple[int, int, int, int] | None:
    if not hexv:
        return None
    h = hexv.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(round(255 * alpha)))


@dataclass
class CaptionSpec:
    font: str
    size: int
    fill: str = "#FFFFFF"
    stroke: str | None = "#000000"
    stroke_px: int = 0
    shadow: dict | None = None
    plate: str | None = None
    plate_radius: int = 0
    plate_pad: tuple[int, int] = (0, 0)
    keyword_fill: str | None = None
    keyword_chip: str | None = None
    keyword_chip_text: str | None = None
    align: str = "centre"
    tilt: float = 0.0
    line_gap: float = 0.12
    case: str = "as_spoken"
    name: str = "default"


@dataclass
class RenderedCaption:
    image: Image.Image                 # RGBA, rotated about the tile centre (= image centre)
    ink_bbox: tuple[int, int, int, int]  # within image, after rotation (QC: safe zone, face)
    lines: list[str] = field(default_factory=list)
    overflow: bool = False             # True if it did not fit max_lines at this size
    tile_w: int = 0                    # UNROTATED tile: widest line ink + plate pads
    tile_h: int = 0                    # UNROTATED tile: lines x metric line box — identical for
                                       # every caption at one size (no-drift anchor)


# ---------------------------------------------------------------- style resolve
def resolve_style(d: dict, style_name: str | None, aspect: str, index: int = 0,
                  size_px: float | None = None, canvas_w: int | None = None) -> CaptionSpec:
    """Design-system style -> concrete spec at this aspect's canvas."""
    import ds  # sibling
    cap = d.get("captions") or {}
    styles, cycle = ds.caption_styles(d)
    pl_style = (ds.placement(d, aspect) or {}).get("style")
    if pl_style:  # a per-aspect look (e.g. a 16:9 landscape_column look) overrides the cycle
        cycle = [pl_style] if isinstance(pl_style, str) else list(pl_style)
    if not style_name:
        style_name = cycle[index % len(cycle)] if cycle else None
    st = dict(styles.get(style_name) or {})
    cw, _ = ds.canvas(d, aspect)
    cw = canvas_w or cw
    k = cw / 1080.0  # sizes in the design system are px at a 1080-wide canvas
    pl = ds.placement(d, aspect)
    if size_px is None:
        size_px = pl.get("size_px") or ((cap.get("size_px_1080") or (d.get("type_scale") or {}).get("base_px_1080") or 58) * k)
    font_key = st.get("font") or "caption"
    tilt_rng = cap.get("tilt_deg") or [0, 0]
    lo, hi = float(tilt_rng[0]), float(tilt_rng[-1])
    mag = lo + (hi - lo) * ((index * 0.618034) % 1.0)  # deterministic spread, never random
    tilt = 0.0 if hi == 0 else (mag if index % 2 == 0 else -mag)
    if cap.get("tilt_cycle"):  # an approved exact rhythm beats the generic alternation
        tilt = float(cap["tilt_cycle"][index % len(cap["tilt_cycle"])])
    aligns = cap.get("align_cycle") or ["centre"]
    sh = st.get("shadow")
    if sh:
        sh = dict(sh)
        sh["color"] = ds.color(d, sh.get("color", "#000000"))
        for kk in ("dx", "dy", "blur"):
            if kk in sh:
                sh[kk] = sh[kk] * k
    pad = st.get("plate_pad_px") or [0, 0]
    return CaptionSpec(
        font=ds.font_path(d, font_key),
        size=int(round(size_px)),
        fill=ds.color(d, st.get("fill", "#FFFFFF")),
        stroke=ds.color(d, st.get("stroke")),
        # a stroke colour with no width = a halo whose width the source never pinned down:
        # 15% of the type size (~6 px at 38 px, the landscape ruling's "white halo adds ~6px")
        stroke_px=int(round((st.get("stroke_px") * k) if st.get("stroke_px") is not None
                            else (0.15 * size_px if st.get("stroke") else 0))),
        shadow=sh,
        plate=ds.color(d, st.get("plate")),
        plate_radius=int(round((st.get("plate_radius_px") or 0) * k)),
        plate_pad=(int(round(pad[0] * k)), int(round(pad[1] * k))),
        keyword_fill=ds.color(d, st.get("keyword_fill")),
        keyword_chip=ds.color(d, st.get("keyword_chip")),
        keyword_chip_text=ds.color(d, st.get("keyword_chip_text")),
        align=aligns[index % len(aligns)],
        tilt=tilt,
        case=cap.get("case") or "as_spoken",
        name=style_name or "default",
    )


# ---------------------------------------------------------------- keyword pick
def pick_keyword(words: list[str]) -> int | None:
    """Index of the most contentful word — numbers first, then Capitalised
    proper nouns / brand words, then the longest non-stopword. The editor can
    always override by marking keywords in captions.json."""
    best, score = None, -1.0
    for i, w in enumerate(words):
        t = re.sub(r"[^\w₹%]", "", w)
        if not t or t.lower() in STOPWORDS:
            continue
        s = len(t)
        if re.search(r"\d", t):
            s += 20
        if w[:1].isupper() and i > 0:
            s += 8
        if any(c.isupper() for c in w[1:]):
            s += 6  # ChatGPT, YouTube
        if s > score:
            best, score = i, s
    return best


# words that lean on the word BEFORE them (Hinglish postpositions / auxiliaries):
# never start a caption card with one
ATTACH_LEFT = set("pe par mein me main ka ki ke ko se hai hain tha thi the thhe na bhi wala wali wale raha rahi rahe "
                  "diya liya gaya gayi hua hui hoga hogi karo karna karne karke dena lena jaata jaati jaate".split())
# a possessive ties to the word AFTER it: never end a card on one
ATTACH_RIGHT = set("ka ki ke mera meri mere tera teri tere apna apni apne uska uski uske iska iski iske the a an my your our "
                   "their his her its".split())
# good places to START a card
STARTERS = set("aur ki jo agar to toh so but and because kyunki lekin phir ya or if when what how why where yeh ye woh "
               "matlab basically".split())


def split_cost(texts: list[str], j: int, target: float) -> float:
    """Cost of breaking a phrase before word j (lower = better). Distance from the even
    split, penalties for stranding a postposition or a possessive, bonuses for a comma
    before or a clause starter after."""
    w = re.sub(r"[^\w]", "", texts[j]).lower()
    prev = texts[j - 1]
    pv = re.sub(r"[^\w]", "", prev).lower()
    c = abs(j - target)
    if w in ATTACH_LEFT:
        c += 2.0
    if pv in ATTACH_RIGHT:
        c += 2.0
    if prev.endswith((",", ";", ":")):
        c -= 1.0
    if w in STARTERS:
        c -= 0.6
    return c


EXPLETIVES = re.compile(r"\b(f)(uck)(ing|ed|er|s)?\b|\b(s)(hi)(t)\b|\b(b)(itc)(h)\b", re.I)


def star_expletives(text: str, d: dict | None = None) -> str:
    """House rule (expletive-is-hers-to-keep): the word stays in the AUDIO, the caption
    stars it — f***ing. `captions.expletives: keep` in a design system turns this off."""
    if ((d or {}).get("captions") or {}).get("expletives") == "keep":
        return text
    def _star(m):
        if m.group(1):
            return m.group(1) + "***" + (m.group(3) or "")
        if m.group(4):
            return m.group(4) + "**" + m.group(6)
        return m.group(7) + "***" + m.group(9)
    return EXPLETIVES.sub(_star, text)


def apply_case(text: str, case: str) -> str:
    if case == "upper":
        return text.upper()
    if case == "lower":
        return text.lower()
    if case == "sentence" and text:
        return text[0].upper() + text[1:]
    return text


# ---------------------------------------------------------------- layout
def _ink_w(font: ImageFont.FreeTypeFont, s: str, sw: int) -> int:
    if not s:
        return 0
    b = font.getbbox(s, stroke_width=sw)
    return b[2] - b[0]


def wrap(words: list[str], font: ImageFont.FreeTypeFont, sw: int, max_w: int,
         max_lines: int | None) -> tuple[list[list[int]], bool]:
    """Greedy wrap on INK width (stroke included). Returns word-index lines."""
    lines: list[list[int]] = []
    cur: list[int] = []
    for i, _ in enumerate(words):
        trial = cur + [i]
        s = " ".join(words[j] for j in trial)
        if cur and _ink_w(font, s, sw) > max_w:
            lines.append(cur)
            cur = [i]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    overflow = bool(max_lines and len(lines) > max_lines)
    return lines, overflow


def render_caption(text: str, spec: CaptionSpec, max_width: int, keywords: list[int] | None = None,
                   max_lines: int | None = 1) -> RenderedCaption:
    """Draw one caption card. The TILE (text + per-line plates) sits exactly at the layer
    centre, so rotating the layer about its centre rotates about the tile centre.
    Size never changes here (uniform size is a no-drift rule): if the text does not fit
    `max_lines` it is flagged `overflow` and the caller SPLITS the card at word timings."""
    words = apply_case(text.strip(), spec.case).split()
    kw = set(keywords or [])
    size = spec.size
    font = _font(spec.font, size)
    sw = spec.stroke_px if spec.stroke else 0
    px, py = spec.plate_pad if spec.plate else (0, 0)
    avail = max(40, max_width - 2 * px)
    lines, overflow = wrap(words, font, sw, avail, max_lines)
    asc, desc = font.getmetrics()
    line_h = int(round((asc + desc) * (1 + spec.line_gap)))
    space_w = font.getlength(" ")
    widths = [_ink_w(font, " ".join(words[j] for j in ln), sw) for ln in lines] or [0]
    cap_top = font.getbbox("H", stroke_width=sw)[1]        # metric box: identical for every line
    desc_bot = font.getbbox("gjpqy", stroke_width=sw)[3]
    tile_w = max(widths) + 2 * px
    tile_h = (len(lines) - 1) * line_h + (desc_bot - cap_top) + 2 * py
    sh = spec.shadow or {}
    blur = int(sh.get("blur", 0) or 0)
    margin = sw + max(px, py) + blur * 2 + int(abs(sh.get("dx", 0) or 0) + abs(sh.get("dy", 0) or 0)) + 8
    W, H = tile_w + 2 * margin, tile_h + 2 * margin
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ink = Image.new("L", (W, H), 0)
    shadow_mask = Image.new("L", (W, H), 0)
    d_layer, d_ink, d_sh = ImageDraw.Draw(layer), ImageDraw.Draw(ink), ImageDraw.Draw(shadow_mask)
    fill = _rgba(spec.fill)
    stroke = _rgba(spec.stroke) if sw else None
    for li, ln in enumerate(lines):
        lw = widths[li]
        if spec.align == "left":
            x0 = margin + px
        elif spec.align == "right":
            x0 = margin + px + (tile_w - 2 * px - lw)
        else:
            x0 = margin + px + (tile_w - 2 * px - lw) / 2
        y0 = margin + py - cap_top + li * line_h      # text origin: plate top of line li = margin + li*line_h
        s_line = " ".join(words[j] for j in ln)
        lb = font.getbbox(s_line, stroke_width=sw)
        if spec.plate:
            box = [x0 - px, y0 + cap_top - py, x0 + lw + px, y0 + desc_bot + py]
            d_layer.rounded_rectangle(box, radius=spec.plate_radius, fill=_rgba(spec.plate))
            d_ink.rounded_rectangle(box, radius=spec.plate_radius, fill=255)
        cx = float(x0 - lb[0])  # ink of the line starts exactly at x0
        for j in ln:
            w = words[j]
            wb = font.getbbox(w, stroke_width=sw)
            is_kw = j in kw
            if is_kw and spec.keyword_chip:
                cp = max(6, size // 7)
                chip = [cx + wb[0] - cp, y0 + cap_top - cp // 2, cx + wb[2] + cp, y0 + desc_bot + cp // 2]
                d_layer.rounded_rectangle(chip, radius=max(4, size // 8), fill=_rgba(spec.keyword_chip))
                d_ink.rounded_rectangle(chip, radius=max(4, size // 8), fill=255)
            col = fill
            if is_kw and spec.keyword_chip and spec.keyword_chip_text:
                col = _rgba(spec.keyword_chip_text)
            elif is_kw and spec.keyword_fill:
                col = _rgba(spec.keyword_fill)
            d_layer.text((cx, y0), w, font=font, fill=col, stroke_width=sw, stroke_fill=stroke)
            d_ink.text((cx, y0), w, font=font, fill=255, stroke_width=sw, stroke_fill=255)
            if spec.shadow:
                d_sh.text((cx, y0), w, font=font, fill=255, stroke_width=sw, stroke_fill=255)
            cx += font.getlength(w) + space_w
    if spec.shadow:
        op = float(sh.get("opacity", 0.5))
        sm = shadow_mask.filter(ImageFilter.GaussianBlur(blur)) if blur else shadow_mask
        sc = _rgba(sh.get("color", "#000000"))
        shadow = Image.new("RGBA", (W, H), sc[:3] + (0,))
        shadow.putalpha(sm.point(lambda v: int(v * op)))
        base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        base.alpha_composite(shadow, (int(sh.get("dx", 0)), int(sh.get("dy", 0))))
        base.alpha_composite(layer)
        layer = base
    if abs(spec.tilt) > 1e-3:
        layer = layer.rotate(spec.tilt, resample=Image.BICUBIC, expand=True)
        ink = ink.rotate(spec.tilt, resample=Image.BICUBIC, expand=True)
    bb = ink.getbbox() or (0, 0, layer.width, layer.height)
    return RenderedCaption(image=layer, ink_bbox=bb, lines=[" ".join(words[j] for j in ln) for ln in lines],
                           overflow=overflow, tile_w=tile_w, tile_h=tile_h)


def one_line_width(text: str, spec: CaptionSpec) -> int:
    """Width the caption needs on ONE line (ink incl. stroke, plus plate pads)."""
    font = _font(spec.font, spec.size)
    sw = spec.stroke_px if spec.stroke else 0
    px = spec.plate_pad[0] if spec.plate else 0
    return _ink_w(font, apply_case(text.strip(), spec.case), sw) + 2 * px


def place_tile(rc: RenderedCaption, cx: float, cy: float) -> tuple[int, int, tuple[int, int, int, int]]:
    """Paste position that puts the (unrotated) tile centre at (cx, cy). Rotation is about
    that centre, so every caption of one class shares one centre whatever its tilt or
    width — the no-drift GATE checks exactly this number."""
    x = int(round(cx - rc.image.width / 2))
    y = int(round(cy - rc.image.height / 2))
    b = rc.ink_bbox
    return x, y, (x + b[0], y + b[1], x + b[2], y + b[3])


# ---------------------------------------------------------------- placement
def place(rc: RenderedCaption, canvas_wh: tuple[int, int], *, cx: float | None = None,
          band: tuple[float, float] | None = None, align: str = "centre",
          y_ink_bottom: float | None = None, y_ink_centre: float | None = None,
          y_ink_top: float | None = None, y_min: float = 0, y_max: float | None = None
          ) -> tuple[int, int, tuple[int, int, int, int], list[str]]:
    """Top-left paste position so the INK box meets the anchor, clamped into the
    band [x0,x1] and [y_min, y_max]. Returns (x, y, ink_box_on_canvas, warnings)."""
    W, H = canvas_wh
    y_max = H if y_max is None else y_max
    ix0, iy0, ix1, iy1 = rc.ink_bbox
    iw, ih = ix1 - ix0, iy1 - iy0
    warns: list[str] = []
    bx0, bx1 = band if band else (0, W)
    if iw > (bx1 - bx0) + 1:
        warns.append(f"ink {iw}px wider than band {bx1 - bx0:.0f}px")
    if align == "left":
        ink_x0 = bx0
    elif align == "right":
        ink_x0 = bx1 - iw
    else:
        c = cx if cx is not None else (bx0 + bx1) / 2
        ink_x0 = c - iw / 2
    ink_x0 = min(max(ink_x0, bx0), max(bx0, bx1 - iw))
    if y_ink_bottom is not None:
        ink_y0 = y_ink_bottom - ih
    elif y_ink_centre is not None:
        ink_y0 = y_ink_centre - ih / 2
    elif y_ink_top is not None:
        ink_y0 = y_ink_top
    else:
        ink_y0 = (H - ih) / 2
    if ink_y0 < y_min:
        warns.append(f"clamped down {y_min - ink_y0:.0f}px to the top floor y{y_min:.0f}")
        ink_y0 = y_min
    if ink_y0 + ih > y_max:
        warns.append(f"clamped up {ink_y0 + ih - y_max:.0f}px to the bottom limit y{y_max:.0f}")
        ink_y0 = max(y_min, y_max - ih)
    x = int(round(ink_x0 - ix0))
    y = int(round(ink_y0 - iy0))
    return x, y, (x + ix0, y + iy0, x + ix1, y + iy1), warns


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    s = max(w / img.width, h / img.height)
    r = img.resize((int(round(img.width * s)), int(round(img.height * s))), Image.LANCZOS)
    x = (r.width - w) // 2
    y = (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ds
    d = ds.load(sys.argv[1] if len(sys.argv) > 1 else None)
    spec = resolve_style(d, None, "9:16", index=0)
    text = "3 naye flavours aaj"
    rc = render_caption(text, spec, max_width=840, keywords=[pick_keyword(text.split())])
    out = "_caption_test.png" if len(sys.argv) < 3 else sys.argv[2]
    rc.image.save(out)
    print(out, rc.ink_bbox, rc.lines)
