# coloro

Shows what in your Figma files follows the design system and what does not, and takes you
straight to the layer that needs fixing. Works with any files and any design system.

[Русская версия](README.ru.md)

## What it does

**Projects.** Each product gets its own project: its own files, token library and history.
Projects never mix, and the same file can belong to several of them.

The interface is three floating panels: projects and files on the left (a checkbox includes a
file, a click on its name shows only that file, each file can be updated, opened in Figma or
limited to some pages), what to look at and what to include on the right, results and search in
the middle. The panels collapse into buttons that keep showing progress and errors; on a narrow
screen they open as dropdowns.

**A summary in every section.** Colors, typography, text, spacing, effects, images and components
each start with their own summary: key numbers with changes since the last update, recommendations
in order of impact with a button that shows those places, the files where it is worst, and a
"how it changed" chart.

**The overall picture in the report.** The main screen: how much colour goes through tokens and styles, how
many stray colours, texts without a style, spacing off the scale, unnamed frames. Below it, a
files × problems map: worst files first, each cell coloured good, needs work or bad. Click a
cell to see the places. Arrows and a "how it changed" chart show whether things got better.

**Colours.** Every colour actually in use (sorted by uses, files, lightness or family, filtered by
family, searchable by hex, token and file), split by what to do about it:
- *almost a token* — indistinguishable by eye, swap for the token;
- *different opacity* — a token's colour at another opacity: needs a token for that opacity;
- *off the system* — far from every token: add it to the system or replace it;
- *not bound* — a token's value typed by hand: bind it, nothing changes visually.

Colour difference is CIEDE2000, the way the eye sees it. Next to it: **gradients** as recipes
(type and stops in order) and **tokens**, showing which tokens of the library are used in the
files and which are never used.

**Search.** One bar at the top: text in any word form and order, in text layers, layer names and
component names (then every instance is found); width and height with a tolerance; a colour with a
picker, eyedropper, opacity and tolerance. The parts combine: "Buy" + 56 × 56 + pink finds exactly
those buttons. Results are screens with a count; a screen opens its layers with links and details
on hover (size, font, colours and where each colour comes from). On the right, filters over the
results with counts: type, component, variant properties (Size, State…), page. Every list copies
with links in one click, ready for a ticket or a message. The search lives in the address, so it
can be bookmarked and shared.

**Typography.** Texts without a style against the system of styles: exactly a style, almost a
style, off the system — with what exactly the system is missing.

**Spacing, radii, strokes.** Numbers against the scale. The scale comes from values already
bound to variables, or a conventional grid when there are none (spacing in steps of 4).

**Shadows and effects.** Hand-made effects against effect styles.

**Images.** One row per image across all places, with a thumbnail: repeats and placeholders.

**Components.** Where they are used, which variants, how many are overridden, which frames
look like detached copies. Optional previews: Figma draws each variant, and the properties
(Size, State…) switch like in Figma, with a large preview of the chosen variant and where it is used.

**A one-file report.** An HTML page with no external files: send it, attach it, print it.

The system of styles, the scale and the effects are inferred from the files themselves. The
colour token reference is a file: W3C Design Tokens, Tokens Studio, a variables export or any CSV.

## Running it

Python 3.9 or newer — the one that ships with macOS is fine. Nothing else to install.

```bash
python3 -m coloro serve
```

A browser opens. Then:

1. **Settings (the gear)** — paste a Figma token (Figma → Settings → Security → Personal access
   tokens, file read access) and, if you have one, the project's token library.
2. **+ in the left panel (Add file)** — paste a link to a file. Pages can be limited by words in
   their names. A new project is in the project menu at the top left.
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
