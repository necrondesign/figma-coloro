# -*- coding: utf-8 -*-
"""Собирает самодостаточный отчёт: тот же интерфейс, что в приложении, но с вшитыми данными.
Такой файл открывается двойным кликом, работает без сервера и без интернета, его можно переслать.
"""
import json, os, sys
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import aggregate

data = aggregate.build()
data.pop("sources", None)          # в пересылаемом отчёте список источников не нужен

html = open(BASE + "/app.html", encoding="utf-8").read()
ph = "/*__DATA__*/ null"
if ph not in html:
    raise SystemExit("в app.html нет плейсхолдера %r" % ph)
out = html.replace(ph, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
path = BASE + "/colors-report.html"
open(path, "w", encoding="utf-8").write(out)

st = data["stats"]
print("files: %d | pages: %d | layers: %s" % (st["files"], st["pages"], f"{st['nodes']:,}"))
print("colors: %d | gradients: %d | tokens: %d" % (st["colors"], st["grads"], st["tokensTotal"]))
print("report: %s (%.1f MB)" % (path, os.path.getsize(path) / 1024 / 1024))
