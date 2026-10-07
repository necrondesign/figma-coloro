"""Командная строка: python3 -m coloro <команда>

  load <ссылка> [--pages stage,...] [--db путь] [--force]   загрузить файл
  stats [--db путь] [--pages stage] [--with-hidden] [--with-archive]   сводка по цветам
  serve [--db путь] [--port 8800] [--no-browser]   открыть coloro в браузере
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import db as dbm
from . import rules
from .figma import Figma, FigmaError
from .load import load_file
from .textnorm import norm

DEFAULT_DB = Path.home() / ".coloro" / "coloro.sqlite"
# Второй путь — там токен хранила прежняя версия coloro.
TOKEN_FILES = (Path.home() / ".config" / "coloro" / "token", Path.home() / ".config" / "figma-colors" / "token")


def read_token() -> str:
    env = os.environ.get("FIGMA_TOKEN", "").strip()
    if env:
        return env
    for p in TOKEN_FILES:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    sys.exit("No Figma access token: put it in ~/.config/coloro/token or the FIGMA_TOKEN variable")


def cmd_load(a) -> None:
    key, _node = rules.parse_link(a.url)
    pats = [p for p in (a.pages or "").split(",") if p.strip()] or None
    con = dbm.connect(a.db)

    def progress(**kw):
        print(f"  {kw['index']}/{kw['total']}  {kw['page']}", flush=True)

    try:
        rep = load_file(con, Figma(read_token()), key, pats, force=a.force, progress=progress)
    except FigmaError as e:
        sys.exit(f"Load failed: {e}")
    print(f"{rep['name']}: {rep['status']}, {len(rep['pages_loaded'])} pages, {rep['nodes']} layers, "
          f"{rep['seconds']} s")
    for f in rep["pages_failed"]:
        print(f"  page failed: {f['page']}: {f['error']}")


def summary(con, pages=None, with_hidden=False, with_archive=False) -> dict:
    """Сводка по цветам с фильтрами — те же счёты, что в отчёте coloro, для сверки."""
    where, args = ["1=1"], []
    if not with_archive:
        where.append("pg.archived = 0")
    if not with_hidden:
        where.append("n.hid = 0")
    pats = [norm(p) for p in (pages or []) if p.strip()]
    if pats:
        where.append("(" + " OR ".join("norm(pg.name) LIKE ?" for _ in pats) + ")")
        args += [f"%{p}%" for p in pats]
    w = " AND ".join(where)
    base = (" FROM paints p JOIN nodes n ON n.file_key = p.file_key AND n.id = p.node_id"
            " JOIN pages pg ON pg.file_key = p.file_key AND pg.page_id = p.page_id WHERE " + w)
    # Цвет — пара (RRGGBB, прозрачность). Градиент считается по разным цветам его стопов:
    # два одинаковых стопа в одном градиенте — одно применение, как в coloro.
    uses_sql = ("SELECT p.kind, p.color, p.alpha, p.src, p.node_id, p.slot, p.grad" + base)
    flat = grad = raw = 0
    colors = set()
    seen_stops = set()
    for kind, color, alpha, src, nid, slot, gid in con.execute(uses_sql, args):
        key = (color, alpha)
        if kind == "stop":
            k = (nid, slot, gid, key)
            if k in seen_stops:
                continue
            seen_stops.add(k)
            grad += 1
        else:
            flat += 1
        colors.add(key)
        if src is None:
            raw += 1
    pw = ["1=1"]
    if not with_archive:
        pw.append("archived = 0")
    pargs = []
    if pats:
        pw.append("(" + " OR ".join("norm(name) LIKE ?" for _ in pats) + ")")
        pargs += [f"%{p}%" for p in pats]
    npages = con.execute("SELECT COUNT(*) FROM pages WHERE " + " AND ".join(pw), pargs).fetchone()[0]
    nw = ["1=1"] + (["pg.archived = 0"] if not with_archive else []) + (["n.hid = 0"] if not with_hidden else [])
    nargs = []
    if pats:
        nw.append("(" + " OR ".join("norm(pg.name) LIKE ?" for _ in pats) + ")")
        nargs += [f"%{p}%" for p in pats]
    layers = con.execute(
        "SELECT COUNT(*) FROM nodes n JOIN pages pg ON pg.file_key = n.file_key AND pg.page_id = n.page_id"
        " WHERE " + " AND ".join(nw), nargs).fetchone()[0]
    recipes = con.execute("SELECT COUNT(DISTINCT p.grad)" + base + " AND p.kind = 'stop'", args).fetchone()[0]
    return {"pages": npages, "layers": layers, "unique colors": len(colors),
            "uses": flat + grad, "in fills and strokes": flat, "in gradients": grad,
            "gradient recipes": recipes, "set by hand": raw}


def cmd_stats(a) -> None:
    con = dbm.connect(a.db)
    pats = [p for p in (a.pages or "").split(",") if p.strip()]
    for k, v in summary(con, pats, a.with_hidden, a.with_archive).items():
        print(f"  {k:<24} {v:>10,}".replace(",", " "))


def cmd_serve(a) -> None:
    from . import server
    server.DB_PATH = Path(a.db)
    server.serve(a.port, open_browser=not a.no_browser)


def main() -> None:
    ap = argparse.ArgumentParser(prog="coloro")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("load")
    p.add_argument("url")
    p.add_argument("--pages")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_load)
    s = sub.add_parser("stats")
    s.add_argument("--db", default=str(DEFAULT_DB))
    s.add_argument("--pages")
    s.add_argument("--with-hidden", action="store_true")
    s.add_argument("--with-archive", action="store_true")
    s.set_defaults(fn=cmd_stats)
    v = sub.add_parser("serve")
    v.add_argument("--db", default=str(DEFAULT_DB))
    v.add_argument("--port", type=int, default=8800)
    v.add_argument("--no-browser", action="store_true")
    v.set_defaults(fn=cmd_serve)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
