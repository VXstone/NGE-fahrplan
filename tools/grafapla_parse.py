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

FARBEN = {"G": "3b65a3", "R": "af3734", "L": "2b7b73", "V": "7a4db2"}   # Güter, Reise, Lok/Leer, violett (6xxxx, z. B. Lötschberg)
FARBE = "3b65a3"
RGB = tuple(int(FARBE[i:i + 2], 16) / 255 for i in (0, 2, 4))


def set_farbe(f):
    global FARBE, RGB
    FARBE = f
    RGB = tuple(int(f[i:i + 2], 16) / 255 for i in (0, 2, 4))


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
            m = re.fullmatch(r"(\d{2,6})(mod|[A-Z]{0,2})'?", txt[0])
            if not m or len(txt) < 2 or not re.fullmatch(r"[+-]?\d{2,4}\*?", txt[1]):
                continue
            x0, y0, x1, y1 = ln["bbox"]
            vp = txt[1] if len(txt) > 1 else ""
            ox, oy = sp[0]["origin"]
            L = (x1 - x0) / max(0.5, abs(ln["dir"][0]))
            # Mitte der Grundlinie der Zugnummer (erstes Wort), dort liegt die Linie knapp darunter
            w0 = (sp[0]["bbox"][2] - sp[0]["bbox"][0]) * len(txt[0]) / max(1, len(sp[0]["text"].strip()))
            mx, my = ox + ln["dir"][0] * w0 / 2, oy + ln["dir"][1] * w0 / 2
            out.add((m.group(1) + m.group(2), vp, round(mx, 1), round(my, 1),
                     round(ln["dir"][0], 3), round(ln["dir"][1], 3)))
    return list(out)


def assign(labs, segs):
    """Zugnummer -> Segment: gleiche Neigung, kleiner Normalabstand.
    Erst nur Segmente, neben denen die Nummer steht; danach (z. B. Bergstrecke Kandersteg–Brig
    mit kurzen, steilen Segmenten) auch solche, in deren Verlängerung sie steht."""
    res = _assign(labs, segs, 5, 5)
    done = set(res.values())
    rest = [l for l in labs if (l[0], l[1]) not in done]
    weit = {i: v for i, v in _assign(rest, segs, 60, 3).items() if i not in res}
    return res, weit


def _assign(labs, segs, over, maxd):
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
            if t < -over or t > L + over:
                continue
            dist = abs((cx - ax) * uy - (cy - ay) * ux)
            if dist < maxd and (best is None or dist < best[0]):
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
        lab, lab_weit = assign(labels(p), segs)

        def x2st(x):
            n, sx = min(stx, key=lambda s: abs(s[1] - x))
            return n if abs(sx - x) < 1.2 else None

        for ch in chains(segs):
            names = Counter(lab[i] for i in ch if i in lab) or Counter(lab_weit[i] for i in ch if i in lab_weit)
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
            trains.append(dict(zug=zug, vp=vp, votes=names.most_common(1)[0][1] if names else 0, linie=Counter(segs[i][4] for i in ch).most_common(1)[0][0],
                               halte=[[s, round(a, 1), round(b, 1)] for s, a, b in pts],
                               seite=pno, rand=(min(y2t(segs[i][1]) for i in ch) < tmin + 1
                                                or max(y2t(segs[i][3]) for i in ch) > tmax - 1)))
    # gleiche Zugnummer über Seiten / Teilstücke zusammenführen
    merged = defaultdict(lambda: dict(vp=Counter(), linie=Counter(), pts={}))
    anon = []
    byz = defaultdict(list)
    for t in trains:
        (byz[t["zug"]] if t["zug"] else anon).append(t)
    keep = []
    for z, ts in byz.items():
        ts.sort(key=lambda t: -t["votes"])
        grp = [ts[0]]
        def ends(t):
            return [(t["halte"][0][0], t["halte"][0][1] % 1440), (t["halte"][-1][0], t["halte"][-1][2] % 1440)]
        changed = True
        while changed:
            changed = False
            for t in ts:
                if any(t is g for g in grp):
                    continue
                if any(a == b and min(abs(ta - tb), 1440 - abs(ta - tb)) <= 2.5
                       for g in grp for a, ta in ends(g) for b, tb in ends(t)):
                    grp.append(t)
                    changed = True
        keep += grp
        anon += [t for t in ts if not any(t is g for g in grp)]
    for t in keep:
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
        # über Mitternacht: an der grössten zeitlichen Lücke aufschneiden
        if len(h) > 1:
            gaps = [((h[(i + 1) % len(h)][1] - h[i][1]) % 1440, i) for i in range(len(h))]
            g, i = max(gaps)
            h = h[i + 1:] + h[:i + 1]
            base, add, last = h[0][1], 0, None
            hh = []
            for s_, a, b in h:
                if last is not None and a + add < last - 1:
                    add += 1440
                a2, b2 = a + add, b + add
                if b2 < a2:
                    b2 += 1440
                hh.append((s_, a2, b2))
                last = a2
            h = hh
        vps = [v for v, _ in m["vp"].most_common()]
        vp = next((v for v in vps if v and not v.startswith(("+", "-"))), vps[0] if vps else "")
        if h and h[0][1] >= 1440 and vp.startswith("+") is False and any(v.startswith("+") for v in vps):
            vp = next(v for v in vps if v.startswith("+"))
        if h and h[0][1] >= 1440:
            h = [(s_, a - 1440, b - 1440) for s_, a, b in h]
        out.append(dict(zug=z, vp=vp, vps=dict(m["vp"]), linie=m["linie"].most_common(1)[0][0],
                        halte=[[s, round(a, 1), round(b, 1)] for s, a, b in h]))
    return dict(feld=Path(fn).stem[1:], titel=titel, zuege=out, ohne_nummer=len(anon))


if __name__ == "__main__":
    import csv
    abbr = {}
    sc = Path(__file__).with_name("stations.csv")
    if sc.exists():
        for r in csv.DictReader(open(sc, encoding="utf-8")):
            if r["abbr"]:
                abbr.setdefault(r["abbr"], r["name"])
    sys.path.insert(0, str(Path(__file__).parent))
    import grafapla_rhb
    st_csv = sys.argv[sys.argv.index("--stations") + 1] if "--stations" in sys.argv else None
    nm = grafapla_rhb.name_matcher(st_csv) if st_csv and Path(st_csv).exists() else None
    res = []
    for fn in sorted(Path(sys.argv[1]).glob("G*.pdf")):
        # Bahnen mit eigenem Layout
        if fn.name.startswith("GRhB") and nm:
            try:
                r = grafapla_rhb.parse_pdf(fn, nm)
            except Exception as e:  # noqa
                r = dict(feld=fn.stem[1:], kat={}, fehler={"RhB": f"{type(e).__name__}: {e}"})
            res.append(r)
            print(r["feld"], {k: len(v["zuege"]) for k, v in r["kat"].items()}, "(RhB)", file=sys.stderr)
            continue
        r = dict(feld=fn.stem[1:], kat={})
        for kat, farbe in FARBEN.items():
            set_farbe(farbe)
            try:
                x = parse_pdf(fn, abbr)
                r["titel"] = x["titel"]
                r["kat"][kat] = dict(zuege=x["zuege"], ohne_nummer=x["ohne_nummer"])
            except Exception as e:  # noqa
                r.setdefault("fehler", {})[kat] = f"{type(e).__name__}: {e}"
        # violette Linien (Nummern 6xxxx, u. a. im Lötschberg-Basistunnel) als Güterzüge führen
        v = r["kat"].pop("V", None)
        if v and "G" in r["kat"]:
            r["kat"]["G"]["zuege"] += v["zuege"]
            r["kat"]["G"]["ohne_nummer"] += v["ohne_nummer"]
        res.append(r)
        print(r["feld"], {k: len(v["zuege"]) for k, v in r["kat"].items()}, r.get("titel", "")[:50], file=sys.stderr)
    import gzip
    op = gzip.open if sys.argv[2].endswith(".gz") else open
    with op(sys.argv[2], "wt", encoding="utf-8") as f:
        json.dump(dict(quelle="tp-info.ch grafische Fahrpläne (SBB Infrastruktur)", felder=res), f, ensure_ascii=False)
