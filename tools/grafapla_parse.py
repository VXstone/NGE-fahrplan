"""Güterzüge aus den grafischen Fahrplänen der SBB (tp-info.ch) extrahieren.

  python grafapla_parse.py <pdf-ordner> <ausgabe.json> [--farbe 3b65a3]

Aufbau der PDFs: Zeit senkrecht (Minutenmarken HH:MM links), Betriebspunkte
waagrecht (Abkürzungen in der Kopfzeile, senkrechte schwarze Linien). Jeder Zug
ist ein Linienzug in seiner Farbe (blau 3b65a3 = Güterzüge 4xxxx–6xxxx, grün
2b7b73 = Lok-/Leerfahrten, rot af3734 = Reisezüge). Die Zugnummer steht als
gedrehter Text gleicher Farbe entlang der Linie, gefolgt von der Verkehrsperiode.

Linienart (Zeichenerklärung SBB 2015): voll = Regelgleis, gestrichelt = rechtes
Gleis, punktiert = 3. Gleis. Buchstaben: F fakultativ, L Lokzug, P mit
Personenbeförderung, R Rangierbewegung.
"""
import json
import math
import re
import sys
from collections import defaultdict, Counter
from pathlib import Path

import pymupdf as fitz

FARBE = sys.argv[sys.argv.index("--farbe") + 1] if "--farbe" in sys.argv else "3b65a3"
RGB = tuple(int(FARBE[i:i + 2], 16) / 255 for i in (0, 2, 4))


def same_col(c):
    return c is not None and all(abs(a - b) < 0.01 for a, b in zip(c, RGB))


def linienart(d):
    ds = str(d or "")
    if ds in ("", "[] 0"):
        return "voll"
    return "gestrichelt" if len(ds.split()) <= 4 else "strichpunkt"


def page_axes(p, words):
    """Zeitachse (y -> Minute, linear) und Stationsspalten (x)."""
    tim = sorted(((w[1] + w[3]) / 2, w[4]) for w in words
                 if re.fullmatch(r"\d\d:\d\d", w[4]) and w[0] < 60)
    if len(tim) < 5:
        return None
    pts, add, last = [], 0, -1
    for y, t in tim:
        m = int(t[:2]) * 60 + int(t[3:]) + add
        if m < last - 600:  # Mitternacht
            add += 1440
            m += 1440
        pts.append((y, m))
        last = m
    n = len(pts)
    my = sum(y for y, _ in pts) / n
    mm = sum(m for _, m in pts) / n
    b = sum((y - my) * (m - mm) for y, m in pts) / sum((y - my) ** 2 for y, _ in pts)
    a = mm - b * my
    y0 = min(y for y, _ in pts) + 2
    vx = sorted({round(it[1].x, 1) for dr in p.get_drawings()
                 if dr.get("color") and max(dr["color"]) < 0.05
                 for it in dr["items"] if it[0] == "l"
                 and abs(it[1].x - it[2].x) < 0.1 and abs(it[1].y - it[2].y) > 150})
    stx = []
    for w in words:
        if w[1] < y0 - 6 and w[1] > 40 and re.fullmatch(r"[A-Z][A-Z0-9]{0,6}", w[4]):
            x = (w[0] + w[2]) / 2
            c = [v for v in vx if abs(v - x) < 30]
            if c:
                stx.append((w[4], min(c, key=lambda v: abs(v - x))))
    # Kopf-/Fusszeilen (SBB, AG …) fallen weg, weil sie keine Spaltenlinie haben
    stx = sorted(set(stx), key=lambda s: s[1])
    return (lambda y: a + b * y), stx, (min(m for _, m in pts), max(m for _, m in pts))


def segments(p):
    segs = set()
    for dr in p.get_drawings():
        if not same_col(dr.get("color")):
            continue
        art = linienart(dr.get("dashes"))
        for it in dr["items"]:
            if it[0] != "l":
                continue
            a, b = it[1], it[2]
            if abs(a.x - b.x) < 0.05 and abs(a.y - b.y) < 0.05:
                continue
            if (a.y, a.x) > (b.y, b.x):  # nach Zeit orientieren
                a, b = b, a
            segs.add((round(a.x, 1), round(a.y, 1), round(b.x, 1), round(b.y, 1), art))
    return sorted(segs, key=lambda s: (s[1], s[0]))


def labels(p):
    out = set()
    for bl in p.get_text("dict")["blocks"]:
        for ln in bl.get("lines", []):
            sp = [s for s in ln["spans"] if "%06x" % s["color"] == FARBE]
            txt = " ".join(s["text"] for s in sp).split()
            if not txt:
                continue
            m = re.fullmatch(r"(\d{4,6})(mod|[A-Z]{0,2})'?", txt[0])
            if not m:
                continue
            x0, y0, x1, y1 = ln["bbox"]
            vp = txt[1] if len(txt) > 1 else ""
            out.add((m.group(1) + m.group(2), vp, round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1),
                     round(ln["dir"][0], 3), round(ln["dir"][1], 3)))
    return list(out)


def assign(labs, segs):
    """Zugnummer -> Segment: gleiche Neigung, kleiner Normalabstand."""
    res = {}
    for zug, vp, cx, cy, dx, dy in labs:
        best = None
        for i, (ax, ay, bx, by, _) in enumerate(segs):
            sx, sy = bx - ax, by - ay
            L = math.hypot(sx, sy)
            if L < 5 or abs(sx) < 1:
                continue
            ux, uy = sx / L, sy / L
            if ux < 0:
                ux, uy = -ux, -uy
            if abs(ux * dy - uy * dx) > 0.03:  # Winkel
                continue
            t = (cx - ax) * ux * (1 if sx > 0 else -1) + (cy - ay) * uy * (1 if sx > 0 else -1)
            if t < -5 or t > L + 5:
                continue
            dist = abs((cx - ax) * uy - (cy - ay) * ux)
            if dist < 12 and (best is None or dist < best[0]):
                best = (dist, i)
        if best:
            res.setdefault(best[1], (zug, vp))
    return res


def chains(segs):
    """Segmente zu Linienzügen verketten (Ende = Anfang, gleiche Fahrtrichtung)."""
    starts = defaultdict(list)
    for i, s in enumerate(segs):
        starts[(s[0], s[1])].append(i)
    used, out = set(), []
    has_pred = {j for s in segs for j in starts.get((s[2], s[3]), [])}
    order = [i for i in range(len(segs)) if i not in has_pred] + list(range(len(segs)))
    for i in order:
        if i in used:
            continue
        ch, cur, sgn = [i], i, 0
        used.add(i)
        while True:
            s = segs[cur]
            if s[2] != s[0]:
                sgn = 1 if s[2] > s[0] else -1
            nxt = [j for j in starts.get((s[2], s[3]), []) if j not in used]
            if not nxt:
                break
            pick = [j for j in nxt if segs[j][2] == segs[j][0] or sgn == 0
                    or (segs[j][2] > segs[j][0]) == (sgn > 0)]
            if not pick:
                break
            cur = pick[0]
            used.add(cur)
            ch.append(cur)
        out.append(ch)
    return out


def parse_pdf(fn, abbr_name):
    d = fitz.open(fn)
    titel = ""
    trains = []
    seen_pages = set()
    for pno, p in enumerate(d):
        words = p.get_text("words")
        if not titel:
            titel = " ".join(w[4] for w in words[:12] if w[1] < 40)
        ax = page_axes(p, words)
        if not ax:
            continue
        y2t, stx, (tmin, tmax) = ax
        if not stx:
            continue
        sig = (round(tmin), round(tmax))
        if sig in seen_pages:  # Seiten sind doppelt gedruckt
            continue
        seen_pages.add(sig)
        segs = segments(p)
        lab = assign(labels(p), segs)

        def x2st(x):
            n, sx = min(stx, key=lambda s: abs(s[1] - x))
            return n if abs(sx - x) < 1.2 else None

        for ch in chains(segs):
            names = Counter(lab[i] for i in ch if i in lab)
            zug, vp = names.most_common(1)[0][0] if names else (None, None)
            pts = []
            for i in ch:
                s = segs[i]
                for x, y in ((s[0], s[1]), (s[2], s[3])):
                    st = x2st(x)
                    t = y2t(y)
                    if st and (not pts or pts[-1][0] != st or abs(pts[-1][2] - t) > 0.05):
                        if pts and pts[-1][0] == st:
                            pts[-1][2] = t  # Haltezeit: Abfahrt nachführen
                        else:
                            pts.append([st, t, t])
            if len(pts) < 2:
                continue
            trains.append(dict(zug=zug, vp=vp, linie=Counter(segs[i][4] for i in ch).most_common(1)[0][0],
                               halte=[[s, round(a, 1), round(b, 1)] for s, a, b in pts],
                               seite=pno, rand=(min(y2t(segs[i][1]) for i in ch) < tmin + 1
                                                or max(y2t(segs[i][3]) for i in ch) > tmax - 1)))
    # gleiche Zugnummer über Seiten / Teilstücke zusammenführen
    merged = defaultdict(lambda: dict(vp=Counter(), linie=Counter(), pts={}))
    anon = []
    for t in trains:
        if not t["zug"]:
            anon.append(t)
            continue
        m = merged[t["zug"]]
        m["vp"][t["vp"]] += 1
        m["linie"][t["linie"]] += 1
        for s, a, b in t["halte"]:
            k = (s, round(a % 1440))
            if not any(s == k2[0] and abs(a % 1440 - k2[1]) < 1.5 for k2 in m["pts"]):
                m["pts"][k] = (s, a % 1440, b % 1440)
    out = []
    for z, m in merged.items():
        h = sorted(m["pts"].values(), key=lambda x: x[1])
        out.append(dict(zug=z, vp=m["vp"].most_common(1)[0][0], linie=m["linie"].most_common(1)[0][0],
                        halte=[[s, round(a, 1), round(b, 1), abbr_name.get(s, "")] for s, a, b in h]))
    return dict(feld=Path(fn).stem[1:], titel=titel, zuege=out, ohne_nummer=len(anon))


if __name__ == "__main__":
    import csv
    abbr = {}
    sc = Path(__file__).with_name("stations.csv")
    if sc.exists():
        for r in csv.DictReader(open(sc, encoding="utf-8")):
            if r["abbr"]:
                abbr.setdefault(r["abbr"], r["name"])
    res = []
    for fn in sorted(Path(sys.argv[1]).glob("G*.pdf")):
        try:
            r = parse_pdf(fn, abbr)
        except Exception as e:  # noqa
            r = dict(feld=fn.stem[1:], fehler=f"{type(e).__name__}: {e}")
        res.append(r)
        print(f"{r['feld']:>5} {len(r.get('zuege', [])):4} Züge, {r.get('ohne_nummer', '-')} ohne Nr  {r.get('titel', r.get('fehler', ''))[:60]}",
              file=sys.stderr)
    json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False)
