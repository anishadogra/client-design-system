# Fonts

Font files are not committed to this repo. The example systems use three families, all free under the SIL Open Font License on [Google Fonts](https://fonts.google.com):

| File | Family | Used by |
|---|---|---|
| `Inter-Bold.ttf` | [Inter](https://fonts.google.com/specimen/Inter) | fallback face for `ds.py sample` labels and unnamed roles |
| `Inter-ExtraBold.ttf`, `Inter-Black.ttf` | Inter | `example-creator` |
| `Poppins-Bold.ttf`, `Poppins-ExtraBold.ttf` | [Poppins](https://fonts.google.com/specimen/Poppins) | `_house` (16:9 column), `example-snack-brand` |
| `Anton-Regular.ttf` | [Anton](https://fonts.google.com/specimen/Anton) | `example-snack-brand` |

Download the families, copy the static `.ttf` weights above into this folder with these exact names, and run `python3 scripts/ds.py validate`. Inter ships as a variable font; the static weights are in its download under `static/`.

A system file may point at any font with a path relative to the repo root (`fonts/MyBrand-Bold.ttf`) or an absolute path. If a named file is missing, the scripts stop and say which one.
