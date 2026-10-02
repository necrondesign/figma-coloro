# -*- coding: utf-8 -*-
"""Fills out/ with made-up data so you can try the app without touching Figma.

    python3 demo/seed.py && python3 app.py

Everything here is invented: file names, page names, layer names, colours.
Delete out/ afterwards to start clean.
"""
import json, os, random

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = BASE + "/out"
random.seed(11)

# Keys are deliberately not shaped like real Figma keys, so nobody mistakes
# demo data for a real file and no scanner flags this file as a leak.
FILES = [
    ("Marketing site",  "demo-marketing-site", ["Stage 1 — Landing", "Stage 2 — Pricing"]),
    ("Mobile app",      "demo-mobile-app", ["Stage 1 — Onboarding", "Stage 2 — Feed", "Stage 3 — Profile"]),
    ("Design system",   "demo-design-system", ["Stage 1 — Foundations", "Stage 2 — Components"]),
    ("Dashboard",       "demo-dashboard", ["Stage 1 — Overview", "Stage 2 — Reports"]),
    ("Email templates", "demo-email-templates", ["Stage 1 — Transactional"]),
]
LAYERS = ["Button / Primary", "Card background", "Section title", "Divider", "Badge",
          "Avatar ring", "Input border", "Nav item", "Chart bar", "Tooltip", "Icon",
          "Table row", "Tag", "Progress track", "Footer link", "Hero panel", "Chip"]
TOKENS = [("color/text/primary", "#1E1E1E"), ("color/text/secondary", "#6B7280"),
          ("color/surface/base", "#FFFFFF"), ("color/surface/raised", "#F7F8FA"),
          ("color/brand/primary", "#0C8CE9"), ("color/brand/hover", "#0A74C2"),
          ("color/accent/success", "#14AE5C"), ("color/accent/warning", "#FF8A1F"),
          ("color/accent/danger", "#E5484D"), ("color/border/subtle", "#E4E7EE"),
          ("color/overlay/dim", "#000000@40%"), ("color/brand/muted", "#C7E2F8")]
FLAT = [v for _, v in TOKENS] + [
    "#2C2C2C", "#383838", "#444444", "#5A5F68", "#8A8F98", "#B1B5BD", "#D7DAE0", "#EBEBEB",
    "#FAFAFA", "#FF5C5C", "#E8604C", "#FF9F43", "#FFC46B", "#FFD166", "#9BD17A", "#2EC4B6",
    "#4CC9F0", "#2B9BD6", "#7B61FF", "#9B8CFF", "#B388EB", "#F15BB5", "#D64C9A",
    "#FFFFFF@60%", "#FFFFFF@15%", "#000000@8%", "#1E1E1E@70%", "#6B7280@30%",
    "#0C8CE9@12%", "#14AE5C@20%", "#E5484D@15%", "#3A3F47", "#C9CDD4"]
GRAD_ONLY = ["#00BBF9", "#9B5DE5", "#06D6A0", "#EF476F", "#118AB2", "#073B4C", "#FFE066",
             "#FF8FA3", "#7AE582", "#80FFDB", "#5E60CE", "#FF70A6", "#FFD6A5", "#BDB2FF", "#A0C4FF"]
GRADS = [["#0C8CE9", "#7B61FF"], ["#FF9F43", "#FFE066"], ["#06D6A0", "#118AB2"],
         ["#F15BB5", "#9B5DE5"], ["#FFFFFF", "#FFFFFF@0%"], ["#EF476F", "#FF8FA3", "#FFD6A5"],
         ["#00BBF9", "#5E60CE", "#9B5DE5"], ["#073B4C", "#118AB2"], ["#7AE582", "#80FFDB"],
         ["#BDB2FF", "#A0C4FF"], ["#FF70A6", "#FFD6A5"]]

def nid(a, b):
    return "%d:%d" % (a, b)

def layers(n, pi, seed):
    return [[nid(100 + pi, 1000 + seed * 9 + k), random.choice(LAYERS),
             random.choice(["RECTANGLE", "FRAME", "TEXT", "ELLIPSE", "VECTOR"]),
             random.choice(["fill", "stroke"])] for k in range(n)]

os.makedirs(OUT, exist_ok=True)
for fname, key, pages in FILES:
    res = {"file": fname, "key": key, "filter": "stage", "pages": [],
           "skipped": ["Cover", "Local components", "Archive"], "errors": [], "nodes": 0}
    for pi, pname in enumerate(pages, 1):
        colors, grads = {}, {}
        nodes = random.randint(2400, 11000)
        for ci, hexv in enumerate(random.sample(FLAT, random.randint(16, 26))):
            flat = random.choice([random.randint(1, 9), random.randint(1, 9),
                                  random.randint(12, 180), random.randint(200, 2400)])
            colors[hexv] = {"flat": flat, "grad": 0, "raw": random.randint(0, flat),
                            "ex": layers(min(flat, random.randint(2, 10)), pi, ci)}
        for gi, stops in enumerate(random.sample(GRADS, random.randint(3, 5))):
            n = random.randint(6, 260)
            grads["→".join(stops)] = {
                "n": n, "type": "GRADIENT_LINEAR",
                "ex": [[nid(200 + pi, 2000 + gi * 5 + k), random.choice(LAYERS),
                        random.choice(["fill", "stroke"])] for k in range(random.randint(2, 7))]}
            for sv in stops:
                e = colors.setdefault(sv, {"flat": 0, "grad": 0, "raw": 0, "ex": []})
                e["grad"] += n
                e["raw"] += n
                if len(e["ex"]) < 6:
                    e["ex"] += layers(2, pi, 500 + gi)
        for gv in random.sample(GRAD_ONLY, random.randint(2, 5)):
            e = colors.setdefault(gv, {"flat": 0, "grad": 0, "raw": 0, "ex": []})
            n = random.randint(3, 90)
            e["grad"] += n
            e["raw"] += n
            if not e["ex"]:
                e["ex"] = layers(3, pi, 900)
        res["pages"].append({"id": nid(1, pi), "name": pname, "nodes": nodes,
                             "colors": colors, "grads": grads})
        res["nodes"] += nodes
    json.dump(res, open("%s/%s@stage.json" % (OUT, key), "w", encoding="utf-8"), ensure_ascii=False)

json.dump({"variables": [{"name": n, "values": {"Light": v}, "collection": "Core"}
                         for n, v in TOKENS]},
          open(BASE + "/tokens.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump([{"key": k, "node": None, "name": n,
            "link": "https://www.figma.com/design/" + k} for n, k, _ in FILES],
          open(BASE + "/sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Demo data written to out/. Run: python3 app.py")
