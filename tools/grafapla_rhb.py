"""Leser für die grafischen Fahrpläne der Rhätischen Bahn (GRhB1…6.pdf).

Aufbau (anders als SBB): Zeit waagrecht (Stundenzahlen und «:10 … :50» oben, Seitentitel «6:00 - 12:00»),
Betriebspunkte senkrecht (Namen links, waagrechte Rasterlinien). Züge als Linien:
blau (0,0,1) = Güterzüge (5xxx), schwarz = Reisezüge, grau = Dienst-/Leerfahrten.
Zugnummer als gedrehter Text in der Farbe der Linie, oft mit «*» davor (Verkehrstage eingeschränkt).
Ausgabe wie grafapla_parse.parse_pdf: {feld, titel, kat: {G|R|L: {zuege, ohne_nummer}}}.
"""
import math
import re
import unicodedata
from collections import Counter, defaultdict

import pymupdf as fitz


def _norm(t):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def kat_of(col, width):
    if col is None:
        return None
    r, g, b = col
    if b > 0.8 and r < 0.2 and g < 0.2:
        return "G"
    if max(col) < 0.05 and width >= 0.7:
        return "R"
    if abs(r - g) < 0.02 and abs(g - b) < 0.02 and 0.5 < r < 0.75 and width >= 1.0:
        return "L"
    return None


def kat_of_text(c):
    r, g, b = (c >> 16) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255
    if b > 0.8 and r < 0.2 and g < 0.2:
        return "G"
    if max(r, g, b) < 0.1:
        return "R"
    if abs(r - g) < 0.05 and 0.4 < r < 0.8:
        return "L"
    return None


def axes(p, words):
    # Zeitachse: Stundenzahlen (grössere Ziffern oben) und «:10»…«:50»
    head = " ".join(w[4] for w in words if w[1] < 70)
    m = re.search(r"(\d{1,2}):00\s*-\s*(\d{1,2}):00", head)
    h0 = int(m.group(1)) if m else 0
    marks = sorted(((w[0] + w[2]) / 2, w[4]) for w in words if 70 < w[1] < 100 and re.fullmatch(r"\d{1,2}|:\d0", w[4]))
    pts, h = [], h0
    for x, t in marks:
        if t.startswith(":"):
            pts.append((x, h * 60 + int(t[1:])))
        else:
            h = int(t)
            pts.append((x, h * 60))
    if len(pts) < 4:
        return None
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    mm = sum(t for _, t in pts) / n
    b = sum((x - mx) * (t - mm) for x, t in pts) / sum((x - mx) ** 2 for x, _ in pts)
    a = mm - b * mx
    x_left = min(x for x, _ in pts) - 40
    # Betriebspunkte: Wörter links, nach Zeile gruppiert; eng stehende Teile zusammenziehen («Seew is» → «Seewis»)
    rows = defaultdict(list)
    for w in words:
        if w[0] < x_left and w[1] > 100 and w[0] > 38:
            rows[round((w[1] + w[3]) / 2)].append(w)
    hz = sorted({round(it[1].y, 1) for dr in p.get_drawings() for it in dr["items"]
                 if it[0] == "l" and abs(it[1].y - it[2].y) < 0.1 and abs(it[1].x - it[2].x) > 300})
    st = []
    for y, ws in rows.items():
        ws.sort(key=lambda w: w[0])
        name = ws[0][4]
        for a_, b_ in zip(ws, ws[1:]):
            name += ("" if b_[0] - a_[2] < 1.5 else " ") + b_[4]
        cand = [g for g in hz if abs(g - y) < 6]
        st.append((name, min(cand, key=lambda g: abs(g - y)) if cand else y))
    st.sort(key=lambda s: s[1])
    return (lambda x: a + b * x), st, (min(t for _, t in pts) - 10, max(t for _, t in pts) + 10)


def parse_pdf(fn, name2abbr):
    d = fitz.open(fn)
    titel = ""
    out = {k: [] for k in "GRL"}
    for p in d:
        words = p.get_text("words")
        if not titel:
            titel = " ".join(w[4] for w in words if w[1] < 60 and w[0] > 1000)
        ax = axes(p, words)
        if not ax:
            continue
        x2t, st, _ = ax

        def y2st(y):
            n, sy = min(st, key=lambda s: abs(s[1] - y))
            return n if abs(sy - y) < 1.5 else None

        segs = defaultdict(set)
        for dr in p.get_drawings():
            k = kat_of(dr.get("color"), dr.get("width") or 0)
            if not k:
                continue
            for it in dr["items"]:
                if it[0] != "l":
                    continue
                a, b = it[1], it[2]
                if abs(a.x - b.x) < 0.05 and abs(a.y - b.y) < 0.05:
                    continue
                if (a.x, a.y) > (b.x, b.y):
                    a, b = b, a
                # Rasterlinien (lange Waagrechte) sind keine Züge
                if abs(a.y - b.y) < 0.1 and abs(a.x - b.x) > 200:
                    continue
                segs[k].add((round(a.x, 1), round(a.y, 1), round(b.x, 1), round(b.y, 1)))
        labs = defaultdict(list)
        for bl in p.get_text("dict")["blocks"]:
            for ln in bl.get("lines", []):
                for s in ln["spans"]:
                    m = re.fullmatch(r"\*?\s*(\d{3,5}[A-Z]?)", s["text"].strip())
                    if not m:
                        continue
                    k = kat_of_text(s["color"])
                    if not k:
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    labs[k].append((m.group(1), "*" in s["text"], (x0 + x1) / 2, (y0 + y1) / 2, ln["dir"]))
        for k in "GRL":
            S = sorted(segs[k], key=lambda s: (s[0], s[1]))
            # Nummer → Segment: Text liegt entlang der Linie, gleiche Neigung, kleiner Abstand
            lab = {}
            for zug, stern, cx, cy, (dx, dy) in labs[k]:
                best = None
                for i, (ax_, ay, bx, by) in enumerate(S):
                    sx, sy = bx - ax_, by - ay
                    L = math.hypot(sx, sy)
                    if L < 5:
                        continue
                    ux, uy = sx / L, sy / L
                    if abs(ux * dy - uy * dx) > 0.08:
                        continue
                    t = (cx - ax_) * ux + (cy - ay) * uy
                    if t < -4 or t > L + 4:
                        continue
                    dist = abs((cx - ax_) * uy - (cy - ay) * ux)
                    if dist < 7 and (best is None or dist < best[0]):
                        best = (dist, i)
                if best:
                    lab.setdefault(best[1], (zug, stern))
            # verketten (Ende = Anfang)
            starts = defaultdict(list)
            for i, s in enumerate(S):
                starts[(s[0], s[1])].append(i)
            pred = {j for s in S for j in starts.get((s[2], s[3]), [])}
            used = set()
            for i in [i for i in range(len(S)) if i not in pred] + list(range(len(S))):
                if i in used:
                    continue
                ch, cur, sgn = [i], i, 0
                used.add(i)
                while True:
                    s = S[cur]
                    if s[3] != s[1]:
                        sgn = 1 if s[3] > s[1] else -1
                    nxt = [j for j in starts.get((s[2], s[3]), []) if j not in used
                           and (S[j][3] == S[j][1] or sgn == 0 or (S[j][3] > S[j][1]) == (sgn > 0))]
                    if not nxt:
                        break
                    cur = nxt[0]
                    used.add(cur)
                    ch.append(cur)
                names = Counter(lab[j] for j in ch if j in lab)
                zug = names.most_common(1)[0][0] if names else None
                pts = []
                for j in ch:
                    s = S[j]
                    for x, y in ((s[0], s[1]), (s[2], s[3])):
                        n = y2st(y)
                        t = x2t(x)
                        if not n:
                            continue
                        if pts and pts[-1][0] == n:
                            pts[-1][2] = t
                        else:
                            pts.append([n, t, t])
                if len(pts) >= 2:
                    out[k].append((zug, pts))
    res = {"feld": fn.stem[1:], "titel": titel, "kat": {}}
    # jedes Linienstück einzeln ausgeben; Zusammenführen und Plausibilisieren macht build_pub
    for k in "GRL":
        zuege, anon = [], 0
        for zg, pts in out[k]:
            if not zg:
                anon += 1
                continue
            zug, stern = zg
            vp = "17*" if stern else "17"
            h = [[name2abbr(n), round(a % 1440, 1), round(b % 1440, 1)] for n, a, b in pts]
            zuege.append(dict(zug=zug, vp=vp, vps={vp: 1}, linie="voll", halte=h))
        res["kat"][k] = dict(zuege=zuege, ohne_nummer=anon)
    return res


def name_matcher(stations_csv):
    import csv
    idx = {}
    for r in csv.DictReader(open(stations_csv, encoding="utf-8")):
        if r["abbr"]:
            idx.setdefault(_norm(r["name"]), r["abbr"])

    def f(name):
        n = re.sub(r"\s*\((B|Abzw|Spw)\)\s*$", "", name.strip())
        k = _norm(n)
        if k in idx:
            return idx[k]
        for kk, ab in idx.items():
            if kk.startswith(k) and len(k) >= 5:
                return ab
        return "?" + n   # unbekannt: Name behalten, mit «?» markiert
    return f


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    nm = name_matcher(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).with_name("stations.csv"))
    for fn in sys.argv[1:2]:
        r = parse_pdf(Path(fn), nm)
        print(r["feld"], r["titel"], {k: (len(v["zuege"]), v["ohne_nummer"]) for k, v in r["kat"].items()})
        for z in sorted(r["kat"]["G"]["zuege"], key=lambda z: z["halte"][0][1])[:6]:
            print("  ", z["zug"], z["vp"], [(s, f"{int(a)//60:02d}:{int(a)%60:02d}") for s, a, b in z["halte"]][:10])
        unk = Counter(s for k in "GRL" for z in r["kat"][k]["zuege"] for s, _, _ in z["halte"] if s.startswith("?"))
        print("unbekannte Namen:", unk.most_common(15))
