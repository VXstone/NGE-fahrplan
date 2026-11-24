"""Leser für grafische Fahrpläne mit waagrechter Zeitachse auf einem grossen Blatt (Schritt C):
MGB (GMGBS/GMGBW, Sommer/Winter), MOB (GMOB), BOB/WAB/JB/BLM/SPB (GBOB), CJ (GCJ, nur mit Textebene).

Aufbau: ein Blatt, mehrere Bänder untereinander. Je Band eine Stundenzeile (0 1 2 … 23 0, grössere Ziffern) über
oder unter dem Band, Betriebspunkte als waagrechte Linien mit dem Namen links (oft Kürzel rechts). Züge sind
schräge Striche in einer Farbe/Strichstärke/Strichart; die Zugnummer steht gedreht entlang des Strichs, bei der
MGB mit Gattung davor («RE 316», «G 4211», «Lr 6513», «A 2410» = Autoverlad Furka).

Vorgehen: Stundenzeilen → x→Minute (linear, je Band die nächste Zeile); waagrechte lange Linien mit Namen links
→ Betriebspunkte; schräge Striche gleicher Art an gemeinsamen Endpunkten zu Linienzügen verketten (kurze
Waagrechte auf einer Stationslinie = Halt, nur wenn beidseits ein Strich gleicher Art anschliesst); Nummer →
nächster Strich gleicher Neigung. Kategorie je Bahn (KONF): Gattung vor der Nummer, sonst Farbe, sonst R.
Ausgabe wie grafapla_rhb.parse_pdf: {feld, titel, kat: {G|R|L: {zuege, ohne_nummer}}}.
"""
import math
import re
from collections import Counter, defaultdict

import pymupdf as fitz

# Gattung → Kategorie. «A» (Autoverlad Furka) wie Vereina nicht als Güterzug: unter L, mit art=Autoverlad.
GATTUNG = {"G": "G", "GEX": "R", "R": "R", "RE": "R", "PE": "R", "IR": "R", "S": "R", "Lr": "L", "DZ": "L",
           "RUB": "L", "Fak": "R", "A": "L"}
KONF = {
    # Farben: Hex → Kategorie (ohne Gattung). None = keine Zugfarbe (Bus, Raster …)
    "MGB": dict(farben={"0000ff": "R", "008000": "R", "ff0000": "R", "ff8000": "L", "808000": "G",
                        "000000": "L", "808080": "R"}, min_breite=0.5),
    "MOB": dict(farben={"000000": "R", "008000": "R", "0000a0": "R", "668000": "R", "ff0000": "R", "808080": "R"},
                min_breite=0.0, start_stunde=0),
    "BOB": dict(farben={"231f20": "R"}, min_breite=0.49, max_breite=0.51),   # 0.67 = Schraffur der Ziffern
    "CJ": dict(farben={"000000": "R", "7f7f7f": "R", "404040": "R", "909090": "R", "9e9e9e": "R"}, min_breite=1.0, start_stunde=0),
}
LAB = re.compile(r"(?:(GEX|RUB|Fak|Lr|DZ|RE|PE|IR|G|R|A|S)\s+(\d{2,5})|(\d{3,5}))(F?)\b")


# Verkehrstage hinter der Nummer (MGB-Schrift «FBS-Bfpl», Zeichen im privaten Bereich):
# \ue021…\ue027 = Wochentag 1…7 (Mo…So, «-» = bis), \ue001 Ⓐ Mo–Fr, \ue003 Ⓒ Sa/So, \ue092 Mo–Sa, \ue094 So;
# übrige Zeichen (Saison, Daten) → zeitweise «*».
VP_ZEICHEN = {"\ue001": "15", "\ue003": "67", "\ue092": "16", "\ue094": "77"}


def vp_aus(rest):
    tage = [ord(c) - 0xE020 for c in rest if 0xE021 <= ord(c) <= 0xE027]
    vp = next((v for c, v in VP_ZEICHEN.items() if c in rest), None)
    if tage:
        vp = f"{tage[0]}{tage[-1]}" if "-" in rest or len(tage) == 1 else f"{min(tage)}{max(tage)}"
    stern = any(0xE070 <= ord(c) <= 0xE07F or 0xE110 <= ord(c) <= 0xE11F for c in rest) or "nur" in rest
    return (vp or "17") + ("*" if stern else "")


def hx(c):
    return "%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)


def bahn_von(fn):
    n = fn.stem[1:].upper()
    for b in ("MGB", "MOB", "BOB", "CJ"):
        if n.startswith(b):
            return b
    return None


def stundenzeilen(words):
    """Zeilen mit fortlaufenden Stundenzahlen (… 22 23 0 1 …) → [(y, f(x)→Minute)]."""
    rows = defaultdict(list)
    for w in words:
        if re.fullmatch(r"\d{1,2}", w[4]) and int(w[4]) <= 24:
            rows[round((w[1] + w[3]) / 2 / 4)].append(w)
    out = []
    for _, ws in rows.items():
        ws.sort(key=lambda w: w[0])
        best, cur = [], [ws[0]]
        for a, b in zip(ws, ws[1:]):
            if (int(b[4]) - int(a[4])) % 24 == 1:
                cur.append(b)
            else:
                best, cur = max(best, cur, key=len), [b]
        best = max(best, cur, key=len)
        if len(best) < 12:
            continue
        dxs = [b[0] - a[0] for a, b in zip(best, best[1:])]
        mdx = sorted(dxs)[len(dxs) // 2]
        if mdx < 20 or any(abs(d - mdx) > 0.1 * mdx for d in dxs):   # Stunden in gleichem Abstand
            continue
        pts, add = [], 0
        for i, w in enumerate(best):
            h = int(w[4]) % 24
            if i and h + add * 24 < pts[-1][1] / 60:
                add += 1
            pts.append(((w[0] + w[2]) / 2, (h + add * 24) * 60))
        n = len(pts)
        mx = sum(x for x, _ in pts) / n
        mm = sum(t for _, t in pts) / n
        b = sum((x - mx) * (t - mm) for x, t in pts) / sum((x - mx) ** 2 for x, _ in pts)
        a = mm - b * mx
        y = sum((w[1] + w[3]) / 2 for w in best) / n
        out.append((y, a, b, pts[0][0], pts[-1][0]))
    return sorted(out)


def einrasten(p, z):
    """Stundenzahlen stehen teils neben der Stundenlinie (BOB): auf senkrechte Linien einer Art einrasten, wenn
    diese bei ≥ 80 % der Stunden innerhalb 15 % des Stundenabstands liegen."""
    y, a, b, xa, xb = z
    sp = 60 / b
    g = defaultdict(set)
    for dr in _drawings(p):
        c = dr.get("color")
        if not c or str(dr.get("dashes") or "[] 0") != "[] 0":
            continue
        for it in dr["items"]:
            if it[0] == "l" and abs(it[1].x - it[2].x) < 0.2 and abs(it[1].y - it[2].y) > 30 \
                    and min(it[1].y, it[2].y) - 60 < y < max(it[1].y, it[2].y) + 60:
                g[(hx(c), round(dr.get("width") or 0, 2))].add(round(it[1].x, 1))
    stunden = [(xa + k * sp) for k in range(int(round((xb - xa) / sp)) + 1)]
    best = None
    for k, xs in g.items():
        xs = sorted(xs)
        paare = []
        for x in stunden:
            n = min(xs, key=lambda u: abs(u - x))
            if abs(n - x) < 0.15 * sp:
                paare.append((n, a + b * x))
        if len(paare) >= 0.8 * len(stunden) and (best is None or len(paare) > len(best)):
            best = paare
    if not best:
        return z
    n = len(best)
    mx = sum(x for x, _ in best) / n
    mm = sum(t for _, t in best) / n
    b2 = sum((x - mx) * (t - round(t / 60) * 60 * 0 - mm) for x, t in best) / sum((x - mx) ** 2 for x, _ in best)
    a2 = mm - b2 * mx
    return (y, a2, b2, xa, xb)


_DR = {}


def _drawings(p):
    k = id(p)
    if k not in _DR:
        _DR.clear()
        _DR[k] = p.get_drawings()
    return _DR[k]


def stundenlinien(p, h0):
    """Ersatz, wenn die Stundenzahlen keine Schrift sind (MOB, CJ 2025): durchgezogene senkrechte Linien in
    gleichem Abstand, 23–26 Stück = Stunden ab h0."""
    g = defaultdict(set)
    for dr in p.get_drawings():
        c = dr.get("color")
        if not c or max(c) > 0.3 or str(dr.get("dashes") or "[] 0") != "[] 0":
            continue
        for it in dr["items"]:
            if it[0] == "l" and abs(it[1].x - it[2].x) < 0.2 and abs(it[1].y - it[2].y) > 100:
                g[round(dr.get("width") or 0, 2)].add(round(it[1].x, 1))
    for _, xs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        xs = sorted(xs)
        if not 23 <= len(xs) <= 26:
            continue
        dxs = [b - a for a, b in zip(xs, xs[1:])]
        m = sorted(dxs)[len(dxs) // 2]
        if m < 30 or any(abs(d - m) > 0.05 * m for d in dxs):
            continue
        b = 60 / m
        return [(0, h0 * 60 - b * xs[0], b, xs[0], xs[-1])]
    return []


def betriebspunkte(p, words, x0, x1):
    """Waagrechte Linien über ≥ 40 % der Zeitachse mit Name links davon → [(y, name, kürzel_rechts)]."""
    hz = Counter()
    for dr in p.get_drawings():
        if not dr.get("color"):
            continue
        for it in dr["items"]:
            if it[0] == "l" and abs(it[1].y - it[2].y) < 0.2:
                lo, hi = sorted((it[1].x, it[2].x))
                hz[round(it[1].y, 1)] += max(0, min(hi, x1) - max(lo, x0))
    ys = sorted(y for y, L in hz.items() if L > 0.4 * (x1 - x0))
    # zusammenfassen (Doppellinien)
    lines = []
    for y in ys:
        if lines and y - lines[-1] < 1.0:
            continue
        lines.append(y)
    rows = defaultdict(list)
    right = defaultdict(list)
    for w in words:
        cy = (w[1] + w[3]) / 2
        if w[2] < x0 - 3 and not re.fullmatch(r"[\d.,]+|km|[+x†]", w[4]):
            rows[round(cy, 0)].append(w)
        elif w[0] > x1 + 1 and re.fullmatch(r"[A-ZÄÖÜ]{2,6}", w[4]):
            right[round(cy, 0)].append(w)
    out = []
    for y in lines:
        cand = [(abs(ry - y), ry) for ry in rows if abs(ry - y) < 6]
        rc = [(abs(k - y), k) for k in right if abs(k - y) < 6]
        ab = right[min(rc)[1]][0][4] if rc else None
        if not cand:
            if ab:      # Name nicht als Schrift (MOB, CJ): nur Kürzel rechts
                out.append((y, None, ab))
            continue
        ry = min(cand)[1]
        ws = sorted(rows[ry], key=lambda w: w[0])
        # nur das Stück direkt links der Zeitachse (Namen stehen rechtsbündig vor Kilometer/Höhe)
        grp = [ws[-1]]
        for w in reversed(ws[:-1]):
            if grp[0][0] - w[2] < 8:
                grp.insert(0, w)
            else:
                break
        name = " ".join(w[4] for w in grp)
        if len(name) < 3 or not re.search(r"[A-Za-zÀ-ü]{3}", name):
            name = None
        if name or ab:
            out.append((y, name, ab))
    return out


class _Gedreht:
    """Seite mit /Rotate: Wörter, Textzeilen und Striche in Bildkoordinaten (wie gezeichnet) liefern."""

    def __init__(self, p, M):
        self.p, self.M = p, M

    def _r(self, x0, y0, x1, y1):
        r = fitz.Rect(x0, y0, x1, y1) * self.M
        return r.x0, r.y0, r.x1, r.y1

    def get_text(self, art):
        if art == "words":
            return [(*self._r(*w[:4]), *w[4:]) for w in self.p.get_text("words")]
        d = self.p.get_text(art)
        for bl in d["blocks"]:
            for ln in bl.get("lines", []):
                ln["bbox"] = self._r(*ln["bbox"])
                v = fitz.Point(ln["dir"]) * self.M - fitz.Point(0, 0) * self.M
                ln["dir"] = (v.x, v.y)
                for sp in ln["spans"]:
                    o = fitz.Point(sp["origin"]) * self.M
                    sp["origin"] = (o.x, o.y)
        return d

    def get_drawings(self):
        out = []
        for dr in self.p.get_drawings():
            dr["items"] = [(it[0], *[q * self.M if isinstance(q, fitz.Point) else q for q in it[1:]]) for it in dr["items"]]
            out.append(dr)
        return out


def parse_pdf(fn, name2abbr, abbrs=None):
    bahn = bahn_von(fn)
    kf = KONF[bahn]
    d = fitz.open(fn)
    p = d[0]
    if p.rotation:
        # gedrehte Seite (MOB): Text und Zeichnung kommen ungedreht, ins Bild drehen
        M = p.rotation_matrix
        p = _Gedreht(p, M)
    words = p.get_text("words")
    res = {"feld": fn.stem[1:], "titel": "", "kat": {k: dict(zuege=[], ohne_nummer=0) for k in "GRL"}}
    if len(words) < 50:
        res["fehler"] = {"Layout": "keine Textebene (Schrift als Kurven), nicht lesbar"}
        return res
    res["titel"] = " ".join(w[4] for w in words if w[1] < 80)[:120]
    zeilen = [einrasten(p, z) for z in stundenzeilen(words)] or stundenlinien(p, kf.get("start_stunde", 0))
    if not zeilen:
        res["fehler"] = {"Layout": "keine Stundenzeile gefunden"}
        return res
    x0 = min(z[3] for z in zeilen) - 5
    x1 = max(z[4] for z in zeilen) + 5
    bp = betriebspunkte(p, words, x0 + 5, x1 - 5)
    ys = [b[0] for b in bp]

    def x2t(x, y):
        z = min(zeilen, key=lambda z: abs(z[0] - y))
        return z[1] + z[2] * x

    def y2bp(y):
        i = min(range(len(ys)), key=lambda i: abs(ys[i] - y)) if ys else None
        return i if i is not None and abs(ys[i] - y) < 1.2 else None

    # Nummern (gedreht entlang der Striche)
    labs = []
    for bl in p.get_text("dict")["blocks"]:
        for ln in bl.get("lines", []):
            dx, dy = ln["dir"]
            if abs(dy) < 0.05:
                continue
            txt = " ".join(s["text"] for s in ln["spans"]).strip()
            m = LAB.match(txt)
            if not m:
                continue
            x_0, y_0, x_1, y_1 = ln["bbox"]
            sp = ln["spans"][0]
            labs.append(dict(vp=vp_aus(txt[m.end():]), gatt=m.group(1), zug=(m.group(2) or m.group(3)) + m.group(4), cx=(x_0 + x_1) / 2, cy=(y_0 + y_1) / 2,
                             ox=sp["origin"][0], oy=sp["origin"][1], w=math.hypot(x_1 - x_0, y_1 - y_0) * 0.9,
                             d=(dx, dy), farbe="%06x" % ln["spans"][0]["color"], txt=txt))
    # Linienstücke je Art (Farbe, Breite, Strichart): zusammenhängende Strecken eines Pfads als Polylinie
    polys = defaultdict(list)
    for dr in p.get_drawings():
        c = dr.get("color")
        if not c:
            continue
        h = hx(c)
        if h not in kf["farben"]:
            continue
        wd = dr.get("width") or 0
        if wd < kf.get("min_breite", 0) or wd > kf.get("max_breite", 99):
            continue
        art = (h, round(wd, 2), str(dr.get("dashes") or "[] 0") != "[] 0")
        cur = []

        def fertig(c):
            if len(c) < 2:
                return
            if c[0][0] > c[-1][0]:
                c = c[::-1]
            # an Richtungswechseln (Wende) teilen: jeder Teil ein eigener Zug
            teile, t, sg = [], [c[0]], 0
            for u, v in zip(c, c[1:]):
                d_ = 0 if abs(v[1] - u[1]) < 0.05 or abs(v[0] - u[0]) < 0.3 else (1 if v[1] > u[1] else -1)
                if d_ and sg and d_ != sg:
                    teile.append(t)
                    t = [u]
                if d_:
                    sg = d_
                t.append(v)
            teile.append(t)
            for t in teile:
                if len(t) >= 2 and t[-1][0] - t[0][0] >= 0.3:
                    polys[art].append(t)

        for it in dr["items"]:
            if it[0] != "l":
                fertig(cur)
                cur = []
                continue
            P_, Q_ = (round(it[1].x, 1), round(it[1].y, 1)), (round(it[2].x, 1), round(it[2].y, 1))
            senk = abs(P_[0] - Q_[0]) < 0.3
            if (senk and abs(P_[1] - Q_[1]) > 40) or min(P_[0], Q_[0]) < x0 or max(P_[0], Q_[0]) > x1:
                fertig(cur)       # Rasterlinie oder ausserhalb der Zeitachse
                cur = []
                continue
            nah = lambda u, v: abs(u[0] - v[0]) < 0.15 and abs(u[1] - v[1]) < 0.15  # noqa: E731
            if cur and nah(cur[-1], P_):
                cur.append(Q_)
            elif cur and nah(cur[-1], Q_):
                cur.append(P_)
            elif cur and nah(cur[0], Q_):
                cur.insert(0, P_)
            elif cur and nah(cur[0], P_):
                cur.insert(0, Q_)
            else:
                fertig(cur)
                cur = sorted([P_, Q_])
        fertig(cur)
    zuege = []
    for art, PL in polys.items():
        # Doppel weg; reine Waagrechte (Halt, Raster) fallen weg, Halte ergeben sich aus der Verbindung
        PL = sorted({tuple(pl) for pl in PL if abs(pl[-1][1] - pl[0][1]) > 0.3})
        for L_ in labs:
            dx, dy = L_["d"]
            w = L_["w"]
            # Bezugspunkte: Mitte der Schrift und Mitte der Grundlinie
            refs = [(L_["cx"], L_["cy"]), (L_["ox"] + dx * w / 2, L_["oy"] + dy * w / 2)]
            best = None
            for k, pl in enumerate(PL):
                if abs(pl[-1][1] - pl[0][1]) <= 0.3:
                    continue
                if pl[-1][0] < L_["cx"] - 40 or pl[0][0] > L_["cx"] + 40:
                    continue
                for n_, (u, v) in enumerate(zip(pl, pl[1:])):
                    sx, sy = v[0] - u[0], v[1] - u[1]
                    Ls = math.hypot(sx, sy)
                    if Ls < 0.05:
                        continue
                    for rx, ry in refs:
                        t = max(0, min(Ls, ((rx - u[0]) * sx + (ry - u[1]) * sy) / Ls))
                        px, py = u[0] + sx * t / Ls, u[1] + sy * t / Ls
                        dist = math.hypot(rx - px, ry - py)
                        if dist > 11 or (best and dist >= best[0]):
                            continue
                        # Neigung über ±10 pt der Polylinie
                        i0, i1 = n_, n_ + 1
                        while i0 > 0 and math.hypot(pl[i0][0] - px, pl[i0][1] - py) < 10:
                            i0 -= 1
                        while i1 < len(pl) - 1 and math.hypot(pl[i1][0] - px, pl[i1][1] - py) < 10:
                            i1 += 1
                        cx_, cy_ = pl[i1][0] - pl[i0][0], pl[i1][1] - pl[i0][1]
                        Lc = math.hypot(cx_, cy_)
                        w_lok = abs(sx / Ls * dy - sy / Ls * dx) if Ls >= 3 else 9
                        w_sehne = abs(cx_ / Lc * dy - cy_ / Lc * dx) if Lc >= 2 else 9
                        if min(w_lok, w_sehne) > 0.15:
                            continue
                        best = (dist, k)
            if best:
                L_.setdefault("kand", []).append((best[0], art, best[1]))
        # Verbinden: Ende → Anfang auf gleicher Höhe, 0…max_halt Minuten später, gleiche Fahrtrichtung
        richt = [0 if abs(pl[-1][1] - pl[0][1]) <= 0.3 else 1 if pl[-1][1] > pl[0][1] else -1 for pl in PL]
        anf = defaultdict(list)
        for k, pl in enumerate(PL):
            anf[round(pl[0][1])].append(k)
        nachf = {}
        kand = []
        for k, pl in enumerate(PL):
            ex, ey = pl[-1]
            for yy in (round(ey) - 1, round(ey), round(ey) + 1):
                for j in anf.get(yy, []):
                    if j == k or richt[j] != richt[k]:
                        continue
                    sx, sy = PL[j][0]
                    if abs(sy - ey) > 0.3:
                        continue
                    dt = x2t(sx, sy) - x2t(ex, ey)
                    if -0.05 <= dt <= kf.get("max_halt", 30):
                        kand.append((dt, k, j))
        hat_vor = set()
        for dt, k, j in sorted(kand):
            if k in nachf or j in hat_vor:
                continue
            nachf[k] = j
            hat_vor.add(j)
        for k0 in range(len(PL)):
            if k0 in hat_vor:
                continue
            ch, k = [k0], k0
            while k in nachf and nachf[k] not in ch:
                k = nachf[k]
                ch.append(k)
            pts = []
            for k in ch:
                for x, y in PL[k]:
                    b_ = y2bp(y)
                    if b_ is None:
                        continue
                    t = x2t(x, y)
                    if pts and pts[-1][0] == b_:
                        pts[-1][2] = t
                    else:
                        pts.append([b_, t, t])
            if len(pts) >= 2:
                zuege.append(dict(art=art, ch=set(ch), pts=pts))
    # Nummer → Linienzug (über das Segment)
    seg2z = {}
    for zi, z in enumerate(zuege):
        for j in z["ch"]:
            seg2z[(z["art"], j)] = zi
    namen = defaultdict(Counter)
    for L_ in labs:
        if not L_.get("kand"):
            continue
        dist, art, j = min(L_["kand"])
        zi = seg2z.get((art, j))
        if zi is not None:
            namen[zi][(L_["gatt"], L_["zug"], L_["vp"])] += 1
    for zi, z in enumerate(zuege):
        h, wd, gestr = z["art"]
        if zi in namen:
            (gatt, zug, vp), _ = namen[zi].most_common(1)[0]
        else:
            gatt, zug, vp = None, None, "17"
        kat = GATTUNG.get(gatt) if gatt else None
        kat = kat or kf["farben"].get(h) or "R"
        if not zug:
            res["kat"][kat]["ohne_nummer"] += 1
            continue
        halte = []
        for k, a, b in z["pts"]:
            y, name, ab = bp[k]
            s = ab if abbrs and ab in abbrs else name2abbr(name) if name else "?" + ab
            if halte and halte[-1][0] == s:
                halte[-1][2] = round(b % 1440, 1)
                continue
            halte.append([s, round(a % 1440, 1), round(b % 1440, 1)])
        if len(halte) < 2:
            continue
        e = dict(zug=zug, vp=vp, vps={vp: 1}, linie="gestrichelt" if gestr else "voll", halte=halte)
        if gatt:
            e["gattung"] = gatt
        if gatt == "A":
            e["art"] = "Autoverlad"
        res["kat"][kat]["zuege"].append(e)
    return res


def mgb_vereinen(winter, sommer):
    """MGB: Winter- und Sommerblatt zu einem Feld «MGB». Winter ist Grundlage (längere Gültigkeit); Züge, die nur
    im Sommerblatt stehen, kommen als zeitweise («*») dazu."""
    if not winter:
        return sommer
    out = dict(winter, feld="MGB", titel="MGB Winter + Sommer", kat={})
    for k in "GRL":
        w = (winter.get("kat") or {}).get(k, dict(zuege=[], ohne_nummer=0))
        s = (sommer or {}).get("kat", {}).get(k, dict(zuege=[], ohne_nummer=0))
        da = {z["zug"] for z in w["zuege"]}
        neu = []
        for z in s["zuege"]:
            if z["zug"] in da:
                continue
            z = dict(z, vp=z["vp"] if z["vp"].endswith("*") else z["vp"] + "*")
            z["vps"] = {z["vp"]: 1}
            neu.append(z)
        out["kat"][k] = dict(zuege=w["zuege"] + neu, ohne_nummer=w["ohne_nummer"])
    return out


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import grafapla_rhb
    nm = grafapla_rhb.name_matcher(sys.argv[2])
    for fn in sys.argv[1:2]:
        r = parse_pdf(Path(fn), nm)
        print(r["feld"], r.get("fehler", ""), {k: (len(v["zuege"]), v["ohne_nummer"]) for k, v in r["kat"].items()})
        for z in sorted(r["kat"]["G"]["zuege"], key=lambda z: z["halte"][0][1])[:8]:
            print("  ", z["zug"], z.get("gattung"), [(s, f"{int(a)//60:02d}:{int(a)%60:02d}") for s, a, b in z["halte"]][:12])
        unk = Counter(s for k in "GRL" for z in r["kat"][k]["zuege"] for s, _, _ in z["halte"] if s.startswith("?"))
        print("unbekannte Namen:", unk.most_common(25))
