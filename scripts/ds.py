#!/usr/bin/env python3
"""
ds.py — load a client's video design system: house defaults deep-merged with the
client file. Every video job reads this FIRST (fonts, palette, caption styles and
placement per aspect, safe zones, sacred rules, open questions).

CLI:
    python3 scripts/ds.py list
    python3 scripts/ds.py show example-snack-brand     # merged JSON
    python3 scripts/ds.py rules example-snack-brand    # brief-ready text: sacred rules, captions, open questions
    python3 scripts/ds.py validate [client]            # schema + fonts/logos exist + style refs resolve
    python3 scripts/ds.py sample example-snack-brand --out s.png [--frame still.jpg]   # sample sheet to approve

Import:
    sys.path.insert(0, "<repo>/scripts")
    import ds;  d = ds.load("example-snack-brand")

Paths inside a system file (fonts, logos) may be relative to the repo root.

Merge rule: dicts merge key by key; a list or scalar in the client file REPLACES the
house value (so a client can shorten a style cycle without inheriting the house one).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SYSTEMS = SKILL / "systems"
SCHEMA = SKILL / "schema" / "design-system.schema.json"
FONTS = SKILL / "fonts"
FALLBACK_FONT = FONTS / "Inter-Bold.ttf"

ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
PLACEMENT_MODES = {"above_head", "title_band", "chest", "elbow", "fixed_y", "bottom",
                   "side_column", "above_strip"}

# aliases people actually type -> file key
# aliases people actually type -> file key. Client aliases belong inside each
# client file (`"aliases": [...]`), not here.
ALIASES = {
    "house": "_house", "_house": "_house",
}

FONTS_HELP = ("Font files are not committed to this repo. Inter, Poppins and Anton are free on "
              "Google Fonts (fonts.google.com); download the weights you need and put the .ttf "
              "files in fonts/ (see fonts/README.md).")


def _log(msg: str) -> None:
    print(f"[ds] {msg}", file=sys.stderr, flush=True)


def resolve_path(p: str | None) -> Path | None:
    """A path in a system file: absolute, or relative to the repo root."""
    if not p:
        return None
    q = Path(p).expanduser()
    return q if q.is_absolute() else SKILL / q


def require_font(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"[ds] font file missing: {p}\n[ds] {FONTS_HELP}")
    return str(p)


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def list_systems() -> list[str]:
    return sorted(p.stem for p in SYSTEMS.glob("*.json"))


def resolve_key(name: str | None) -> str:
    if not name:
        return "_house"
    k = name.strip().lower()
    if (SYSTEMS / f"{k}.json").exists():
        return k
    if k in ALIASES:
        return ALIASES[k]
    for p in SYSTEMS.glob("*.json"):  # aliases declared inside the files
        try:
            if k in [a.lower() for a in json.loads(p.read_text()).get("aliases", [])]:
                return p.stem
        except Exception:  # noqa: BLE001
            pass
    raise SystemExit(f"[ds] no design system for '{name}'. Known: {', '.join(list_systems())}")


def load_raw(key: str) -> dict:
    p = SYSTEMS / f"{key}.json"
    if not p.exists():
        raise SystemExit(f"[ds] missing {p}")
    return json.loads(p.read_text())


def load(name: str | None = None) -> dict:
    """Merged design system (house <- client). name None/'_house' -> house only."""
    key = resolve_key(name)
    house = load_raw("_house") if (SYSTEMS / "_house.json").exists() else {}
    if key == "_house":
        d = dict(house)
    else:
        client = load_raw(key)
        parent = client.get("inherits", "_house")
        base = house if parent in (None, "_house") else load(parent)
        d = deep_merge(base, client)
        # house bookkeeping must not leak into the client identity
        for k in ("client", "status", "display_name", "updated", "summary", "inherits"):
            if k in client:
                d[k] = client[k]
        d["sources"] = list(dict.fromkeys((house.get("sources") or []) + (client.get("sources") or [])))
        d["open_questions"] = list(dict.fromkeys((house.get("open_questions") or []) + (client.get("open_questions") or [])))
        d["sacred_rules"] = list(dict.fromkeys((house.get("sacred_rules") or []) + (client.get("sacred_rules") or [])))
    d["_key"] = key
    return d


# ---------------------------------------------------------------- accessors
def canvas(d: dict, aspect: str) -> tuple[int, int]:
    c = (d.get("layout") or {}).get("canvas", {}).get(aspect)
    if c:
        return int(c[0]), int(c[1])
    if aspect in ASPECTS:
        return ASPECTS[aspect]
    a, b = (float(x) for x in aspect.split(":"))
    return (1080, int(round(1080 * b / a))) if b >= a else (int(round(1080 * a / b)), 1080)


def font_path(d: dict, role: str = "caption") -> str:
    f = (d.get("fonts") or {}).get(role) or (d.get("fonts") or {}).get("caption") or {}
    p = resolve_path(f.get("file"))
    if p and p.exists():
        return str(p)
    if p:
        require_font(p)  # a named file that is missing is an error, not a silent swap
    return require_font(FALLBACK_FONT)


def color(d: dict, value: str | None) -> str | None:
    """Style colours may name a palette entry ('ink') or give a hex."""
    if value is None:
        return None
    if isinstance(value, str) and value.startswith("#"):
        return value
    return (d.get("palette") or {}).get(value, value)


def caption_styles(d: dict) -> tuple[dict, list[str]]:
    cap = d.get("captions") or {}
    styles = cap.get("styles") or {}
    cycle = cap.get("style_cycle") or (list(styles)[:1] if styles else [])
    return styles, cycle


def placement(d: dict, aspect: str) -> dict:
    pl = ((d.get("captions") or {}).get("placement") or {})
    return pl.get(aspect) or pl.get("default") or {}


def safe_zone(d: dict, aspect: str) -> dict:
    return ((d.get("layout") or {}).get("safe_zones") or {}).get(aspect) or {}


def logo(d: dict, aspect: str) -> dict | None:
    lg = ((d.get("brand") or {}).get("logo") or {})
    files = [dict(f, path=str(resolve_path(f["path"]))) for f in (lg.get("files") or [])
             if f.get("path") and resolve_path(f["path"]).exists()]
    if not files:
        return None
    pl = (lg.get("placement") or {})
    spot = pl.get(aspect) or pl.get("default")
    if not spot:
        return None
    return {"path": files[0]["path"], "files": files, **spot,
            "every_frame": lg.get("every_frame")}


def rules_text(d: dict) -> str:
    """Short brief block: the things a job must honour, quoted not paraphrased."""
    out = [f"DESIGN SYSTEM — {d.get('display_name') or d.get('_key')} ({d.get('status')}, updated {d.get('updated')})"]
    if d.get("summary"):
        out.append(d["summary"])
    sr = d.get("sacred_rules") or []
    if sr:
        out.append("Sacred rules (verbatim):")
        out += [f"  - {r}" for r in sr]
    cap = d.get("captions") or {}
    if cap:
        out.append(f"Captions: policy={cap.get('policy')!r}; language={cap.get('language')!r}; "
                   f"cycle={cap.get('style_cycle')}; tilt={cap.get('tilt_deg')}")
        for a, p in (cap.get("placement") or {}).items():
            out.append(f"  {a}: {p.get('mode')} fallback={p.get('fallback')} {p.get('notes') or ''}".rstrip())
    oq = d.get("open_questions") or []
    if oq:
        out.append("OPEN — ask, never assume:")
        out += [f"  - {q}" for q in oq]
    return "\n".join(out)


# ---------------------------------------------------------------- validation
def validate(key: str) -> list[str]:
    errs: list[str] = []
    raw = load_raw(key)
    try:
        import jsonschema  # type: ignore
        jsonschema.validate(raw, json.loads(SCHEMA.read_text()))
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        errs.append(f"schema: {str(e).splitlines()[0]}")
    d = load(key)
    for role, f in (d.get("fonts") or {}).items():
        p = (f or {}).get("file")
        if p and not resolve_path(p).exists():
            errs.append(f"font {role}: file does not exist: {p} (see fonts/README.md)")
    for f in ((d.get("brand") or {}).get("logo") or {}).get("files") or []:
        if f.get("path") and not resolve_path(f["path"]).exists():
            errs.append(f"logo file does not exist: {f['path']}")
    for name, hexv in (d.get("palette") or {}).items():
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(hexv)):
            errs.append(f"palette {name}: not #RRGGBB: {hexv}")
    styles, cycle = caption_styles(d)
    for s in cycle:
        if s not in styles:
            errs.append(f"style_cycle names unknown style '{s}'")
    for sname, st in styles.items():
        fk = st.get("font")
        if fk and fk not in (d.get("fonts") or {}):
            errs.append(f"style {sname}: font key '{fk}' not in fonts")
        for ck in ("fill", "stroke", "plate", "keyword_fill", "keyword_chip", "keyword_chip_text"):
            v = st.get(ck)
            if v and not str(color(d, v)).startswith("#"):
                errs.append(f"style {sname}.{ck}: '{v}' is neither hex nor a palette name")
    for a, p in ((d.get("captions") or {}).get("placement") or {}).items():
        for m in [p.get("mode")] + list(p.get("fallback") or []):
            if m and m not in PLACEMENT_MODES:
                errs.append(f"placement {a}: unknown mode '{m}'")
    return errs


# ---------------------------------------------------------------- sample sheet
def sample(key: str, out: str, frame: str | None = None) -> str:
    """Palette + type scale + every caption style in every aspect — the 'approve
    visual samples' step. Uses the same caption engine the renderer uses."""
    from PIL import Image, ImageDraw, ImageFont
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import captions as capeng  # noqa: E402

    d = load(key)
    styles, cycle = caption_styles(d)
    names = list(dict.fromkeys(cycle + list(styles)))[:6] or ["default"]
    W = 1800
    rows = []
    # palette strip
    pal = d.get("palette") or {}
    lab = ImageFont.truetype(require_font(FALLBACK_FONT), 17)
    per_row, cell = 9, W // 9
    nrows = max(1, -(-len(pal) // per_row))
    strip = Image.new("RGB", (W, 150 * nrows), "white")
    dr = ImageDraw.Draw(strip)
    for i, (n, h) in enumerate(pal.items()):
        x, y = 20 + (i % per_row) * cell, 16 + (i // per_row) * 150
        dr.rectangle([x, y, x + cell - 40, y + 70], fill=h, outline="#999999")
        name = n if len(n) <= 18 else n[:17] + "…"
        dr.text((x, y + 78), f"{name}\n{h}", fill="#222222", font=lab)
    rows.append(strip)
    # type scale
    ts = d.get("type_scale") or {}
    base, ratio = ts.get("base_px_1080"), ts.get("ratio")
    if base and ratio:
        sc = Image.new("RGB", (W, 260), "white")
        dr = ImageDraw.Draw(sc)
        fnt = font_path(d, "display") if (d.get("fonts") or {}).get("display") else font_path(d)
        x = 20
        for k in (-2, -1, 0, 1, 2):
            px = base * (ratio ** k)
            f = ImageFont.truetype(fnt, max(8, int(round(px * 0.5))))
            dr.text((x, 40), "Aa", fill="#141414", font=f)
            dr.text((x, 210), f"{px:.0f}px", fill="#666666", font=lab)
            x += int(px * 0.5 * 1.6) + 40
        rows.append(sc)
    # caption styles on a frame, per aspect
    bg = Image.open(frame).convert("RGB") if frame else None
    for aspect in ("9:16", "16:9"):
        cw, ch = canvas(d, aspect)
        tiles = []
        for i, sname in enumerate(names):
            if bg is not None:
                t = capeng.cover(bg, cw, ch)
            else:
                t = Image.new("RGB", (cw, ch), (200, 200, 200))
            spec = capeng.resolve_style(d, sname, aspect, index=i)
            img = capeng.render_caption("Sample caption with keyword", keywords=[3],
                                        spec=spec, max_width=int(cw * 0.66))
            t = t.convert("RGBA")
            t.alpha_composite(img.image, (max(0, (cw - img.image.width) // 2), int(ch * 0.2)))
            dr = ImageDraw.Draw(t)
            dr.text((20, ch - 60), f"{aspect} · {sname}", fill="#FF00FF", font=ImageFont.truetype(str(FALLBACK_FONT), 36))
            tiles.append(t.convert("RGB"))
        th = 520 if aspect == "9:16" else 300
        tiles = [t.resize((int(t.width * th / t.height), th)) for t in tiles]
        row = Image.new("RGB", (W, th + 20), "white")
        x = 10
        for t in tiles:
            if x + t.width > W:
                break
            row.paste(t, (x, 10))
            x += t.width + 10
        rows.append(row)
    H = sum(r.height for r in rows)
    sheet = Image.new("RGB", (W, H), "white")
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("show"); s.add_argument("client")
    r = sub.add_parser("rules"); r.add_argument("client")
    v = sub.add_parser("validate"); v.add_argument("client", nargs="?")
    sm = sub.add_parser("sample"); sm.add_argument("client"); sm.add_argument("--out", required=True); sm.add_argument("--frame")
    a = ap.parse_args()
    if a.cmd == "list":
        for k in list_systems():
            raw = load_raw(k)
            print(f"{k:12s} {raw.get('status', ''):9s} {raw.get('display_name', '')}")
    elif a.cmd == "show":
        print(json.dumps(load(a.client), indent=2, ensure_ascii=False))
    elif a.cmd == "rules":
        print(rules_text(load(a.client)))
    elif a.cmd == "validate":
        keys = [resolve_key(a.client)] if a.client else list_systems()
        bad = 0
        for k in keys:
            errs = validate(k)
            print(f"{k}: {'OK' if not errs else str(len(errs)) + ' problem(s)'}")
            for e in errs:
                print(f"   - {e}")
            bad += len(errs)
        sys.exit(1 if bad else 0)
    elif a.cmd == "sample":
        print(sample(resolve_key(a.client), a.out, a.frame))


if __name__ == "__main__":
    main()
