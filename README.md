# coloro

Shows what in your Figma files follows the design system and what does not, and takes you
straight to the layer that needs fixing. Works with any files and any design system.

[Русская версия](README.ru.md)

## What it does

**The overall picture.** The main screen: how much colour goes through tokens and styles, how
many stray colours, texts without a style, spacing off the scale, unnamed frames. Below it, a
files × problems map: worst files first, each cell coloured good, needs work or bad. Click a
cell to see the places. Arrows and a "how it changed" chart show whether things got better.

**Colours.** Every colour actually in use, split by what to do about it:
- *almost a token* — indistinguishable by eye, swap for the token;
- *different opacity* — a token's colour at another opacity: needs a token for that opacity;
- *off the system* — far from every token: add it to the system or replace it;
- *not bound* — a token's value typed by hand: bind it, nothing changes visually.

Colour difference is CIEDE2000, the way the eye sees it.

**Search.** Text in any word form and any order, size with a tolerance, a colour and the shades
close to it. Results are screens with a count; open a screen to see the layers with links.

**Typography.** Texts without a style against the system of styles: exactly a style, almost a
style, off the system — with what exactly the system is missing.

**Spacing, radii, strokes.** Numbers against the scale. The scale comes from values already
bound to variables, or a conventional grid when there are none (spacing in steps of 4).

**Shadows and effects.** Hand-made effects against effect styles.

**Images.** One row per image across all places, with a thumbnail: repeats and placeholders.

**Components.** Where they are used, which variants, how many are overridden, which frames
look like detached copies.

**A one-file report.** An HTML page with no external files: send it, attach it, print it.

The system of styles, the scale and the effects are inferred from the files themselves. The
colour token reference is a file: W3C Design Tokens, Tokens Studio, a variables export or any CSV.

## Running it

Python 3.9 or newer — the one that ships with macOS is fine. Nothing else to install.

```bash
python3 -m coloro serve
```

A browser opens. Then:

1. **Settings** — paste a Figma token (Figma → Settings → Security → Personal access tokens,
   file read access) and, if you have one, the token reference file.
2. **Sources** — paste links to files. Pages can be limited by words in their names.
3. **Update.** The first load of a big file takes minutes, an update with no changes takes
   seconds: coloro asks Figma only for the file version and downloads changed pages only.

Instead of the interface, the token can live in `~/.config/coloro/token` or in the
`FIGMA_TOKEN` environment variable.

From the terminal:

```bash
python3 -m coloro load "https://www.figma.com/design/…" --pages stage
```

```bash
python3 -m coloro stats
```

## Filters

Loading keeps everything — hidden layers, archived pages, utility sections — with labels.
Filters decide what to count when you look, and they are shared by every screen, so the
numbers always agree. By default coloro counts what is visible on screen:

| Filter | Default |
|---|---|
| Hidden layers | not counted |
| Archived pages (archive in the name) | not counted |
| Layers inside components | counted — they are visible |
| Pages by name | all |
| Sections by name | none excluded |
| Date a layer appeared | all time |

Texts without a style, spacing, effects and unnamed frames are counted only for what was placed
on the screen by hand: inside a component the library sets them, and they cannot be fixed there.

## Where the data lives

Everything stays on your computer in one file, `~/.coloro/coloro.sqlite`. Nothing is sent
anywhere except requests to Figma. The server listens on `127.0.0.1` only and refuses requests
from other pages. The token is stored in `~/.config/coloro/token`, readable by you only, and is
never sent back to the interface.

Removing a link removes its data. To remove everything, delete the database file.

## Scale

Tested on 32 working files at once — 4.3 million layers:

| | |
|---|---|
| Loading all of them | 20 minutes, no failures |
| Updating with no changes | 8 seconds |
| Overall picture | 4 s the first time, instant afterwards |
| Colours | 1 s |
| Text and size search | 0.6 s |

## Development

```bash
python3 -m unittest discover -s tests
```

The plan and the decisions behind it: [docs/PLAN.ru.md](docs/PLAN.ru.md) (in Russian).

## License

MIT — see [LICENSE](LICENSE).
