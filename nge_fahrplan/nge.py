"""spec.json -> Netzgrafik-Editor-JSON.

Umsetzung der Regeln aus dem NGE_JSON_Cookbook:
* Metadaten 1:1 aus einem echten NGE-Export (eingebettet: netzgrafik_default.json
  des netzgrafik-editor-frontend, Apache-2.0)
* PortAlignment Top=0, Bottom=1, Left=2, Right=3 aus der Geometrie
* Transitions an jedem Zwischenhalt (isNonStopTransit fuer Durchfahrten)
* backwardTravelTime separat, Symmetrie-Flags aus den echten Zeiten abgeleitet
* consecutiveTime = absolute Minuten (Fahrzeiten > 60' korrekt)

Spec-Format (alle Zeiten in absoluten Minuten ab Mitternacht, > 59 erlaubt):

    {"name": "...",
     "positions": {"NE": [x, y]},            # optional, Handverschiebungen
     "trainruns": [
       {"name": "66 BN-CF", "category": "IR", "frequency": "60",
        "timeCategory": "7/24", "direction": "round_trip",
        "stops": [{"at": "BN", "dep": 13}, {"at": "KZ", "arr": 30, "dep": 31},
                  {"at": "XY", "arr": 40, "dep": 40, "pass": true},
                  {"at": "CF", "arr": 77, "skipped": 2}],
        "back":  [{"at": "CF", "dep": 103}, ..., {"at": "BN", "arr": 167}]}]}

``back`` (Rueckfahrt in Fahrtrichtung) ist optional – ohne ``back`` wird an der
Minute-0-Achse gespiegelt (Schweizer Symmetrie). ``skipped`` = nicht als Knoten
modellierte Halte vor diesem Halt (-> numberOfStops).
"""
from __future__ import annotations

import copy
import json
import math
from importlib import resources
from pathlib import Path

from .didok import StationDB

TOP, BOTTOM, LEFT, RIGHT = 0, 1, 2, 3
GRID = 32
TEXT_H = 28

HALTEZEITEN = {
    "HaltezeitIPV": {"haltezeit": 3, "no_halt": False},
    "HaltezeitA": {"haltezeit": 2, "no_halt": False},
    "HaltezeitB": {"haltezeit": 2, "no_halt": False},
    "HaltezeitC": {"haltezeit": 1, "no_halt": False},
    "HaltezeitD": {"haltezeit": 1, "no_halt": False},
    "HaltezeitUncategorized": {"haltezeit": 0, "no_halt": True},
}


def default_metadata() -> dict:
    return json.loads(resources.files(__package__).joinpath("metadata_default.json").read_text("utf-8"))


def align(dx: float, dy: float) -> int:
    if abs(dx) >= abs(dy):
        return RIGHT if dx > 0 else LEFT
    return BOTTOM if dy > 0 else TOP


class Projection:
    """WGS84 -> NGE-Koordinaten (Nord oben). ``upk`` = Einheiten pro km."""

    def __init__(self, lat0: float = 46.8, lon0: float = 8.2, upk: float = 80):
        self.lat0, self.lon0, self.upk = lat0, lon0, upk
        self.klon = 111.32 * math.cos(math.radians(lat0))

    def __call__(self, lat: float, lon: float) -> tuple[int, int]:
        x = (lon - self.lon0) * self.klon * self.upk
        y = -(lat - self.lat0) * 111.32 * self.upk
        return round(x / GRID) * GRID, round(y / GRID) * GRID


def _tm(t: int | None, lock: bool = False) -> dict:
    t = 0 if t is None else int(t)
    return {"lock": lock, "time": t % 60, "warning": None, "consecutiveTime": t}


class Builder:
    def __init__(self, db: StationDB | None = None, metadata: dict | None = None,
                 upk: float = 80, positions: dict | None = None, min_dist: float = 4 * GRID,
                 layout: str = "geo", spacing: float = 8 * GRID):
        self.db = db
        self.meta = metadata or default_metadata()
        self.upk = upk
        self.positions = {k.upper(): v for k, v in (positions or {}).items()}
        self.min_dist = min_dist
        self.layout = layout
        self.spacing = spacing
        self.nodes: dict[str, dict] = {}
        self.sections: list[dict] = []
        self.trainruns: list[dict] = []
        self.resources: list[dict] = []
        self._id = {"node": 0, "port": 0, "section": 0, "trainrun": 0, "resource": 0, "transition": 0}
        self._latlon: dict[str, tuple] = {}
        self.warnings: list[str] = []

    def _next(self, kind: str) -> int:
        v = self._id[kind]
        self._id[kind] += 1
        return v

    def _resource(self, capacity: int = 2) -> int:
        rid = self._next("resource")
        self.resources.append({"id": rid, "capacity": capacity})
        return rid

    # ---------- Kategorien aus den Metadaten ----------
    def _meta_id(self, table: str, short: str) -> int:
        for e in self.meta[table]:
            if str(e["shortName"]) == str(short):
                return e["id"]
        raise KeyError(f"{table}: '{short}' unbekannt – vorhanden: "
                       + ", ".join(str(e["shortName"]) for e in self.meta[table]))

    # ---------- Knoten ----------
    def node(self, abbr: str, name: str | None = None) -> dict:
        key = abbr.upper()
        if key in self.nodes:
            return self.nodes[key]
        st = None
        if self.db:
            try:
                st = self.db.resolve(abbr)
            except KeyError as e:
                self.warnings.append(str(e))
        full = name or (st.name if st else abbr)
        bp = st.abbr if st and st.abbr else abbr
        if st and st.lat is not None:
            self._latlon[key] = (st.lat, st.lon)
        elif key not in self.positions:
            self.warnings.append(f"{abbr}: keine Koordinate – Position bitte in NGE setzen")
        n = {
            "id": self._next("node"), "betriebspunktName": bp, "fullName": full,
            "positionX": 0, "positionY": 0, "ports": [], "transitions": [], "connections": [],
            "resourceId": self._resource(), "perronkanten": 2, "connectionTime": 3,
            "trainrunCategoryHaltezeiten": copy.deepcopy(HALTEZEITEN),
            "symmetryAxis": None, "warnings": None, "labelIds": [],
        }
        self.nodes[key] = n
        return n

    def _place_nodes(self):
        if self.layout == "perlschnur":
            return self._place_pearls()
        if self._latlon:
            lats = [v[0] for v in self._latlon.values()]
            lons = [v[1] for v in self._latlon.values()]
            proj = Projection((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2, self.upk)
        placed = []
        unknown = 0
        for key, n in self.nodes.items():
            if key in self.positions:
                n["positionX"], n["positionY"] = map(int, self.positions[key])
            elif key in self._latlon:
                x, y = proj(*self._latlon[key])
                # Mindestabstand: bei Kollision in 32er-Schritten nach unten ausweichen
                while any(abs(x - px) < self.min_dist and abs(y - py) < 3 * GRID for px, py in placed):
                    y += 3 * GRID
                n["positionX"], n["positionY"] = x, y
            else:
                n["positionX"], n["positionY"] = -2000, unknown * 4 * GRID
                unknown += 1
            placed.append((n["positionX"], n["positionY"]))


    # ---------- Layout "Perlschnur" ----------
    def _place_pearls(self):
        """Schematisches Layout. Knotenbahnhoefe (mind. 3 Nachbarn) behalten ihre
        geografische Lage, der Massstab wird so gewaehlt, dass die Bahnhoefe dazwischen
        etwa ``spacing`` auseinander liegen; sie werden gleichmaessig auf der Geraden
        zwischen den beiden Knoten aufgereiht. Aeste mit offenem Ende werden als
        Perlschnur in festem Abstand in geografischer Richtung (auf 45 Grad gerundet,
        waagrecht/senkrecht bevorzugt) gelegt. Fest vorgegebene ``positions`` bleiben."""
        S = self.spacing
        by_id = {n["id"]: k for k, n in self.nodes.items()}
        nb: dict[str, set] = {k: set() for k in self.nodes}
        lines_at: dict[str, set] = {k: set() for k in self.nodes}
        for sec in self.sections:
            a, b = by_id[sec["sourceNodeId"]], by_id[sec["targetNodeId"]]
            nb[a].add(b); nb[b].add(a)
            lines_at[a].add(sec["trainrunId"]); lines_at[b].add(sec["trainrunId"])
        # Geografie in km (fehlende Koordinate: Mittel der Nachbarn)
        geo: dict[str, tuple] = {}
        if self._latlon:
            lats = [v[0] for v in self._latlon.values()]
            lons = [v[1] for v in self._latlon.values()]
            lat0, lon0 = (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2
            klon = 111.32 * math.cos(math.radians(lat0))
            geo = {k: ((lon - lon0) * klon, -(lat - lat0) * 111.32)
                   for k, (lat, lon) in self._latlon.items() if k in self.nodes}
        for _ in range(5):
            for k in self.nodes:
                if k not in geo:
                    g = [geo[x] for x in nb[k] if x in geo]
                    if g:
                        geo[k] = (sum(x for x, _ in g) / len(g), sum(y for _, y in g) / len(g))
        for k in self.nodes:
            geo.setdefault(k, (0.0, 0.0))

        def size(k):    # grobe Knotengroesse (B, H), wie NGE sie zeichnet
            return 3 * GRID, max(2 * GRID, len(lines_at[k]) * GRID + TEXT_H)

        def snap(v):
            return round(v / GRID) * GRID

        # Ketten zwischen Knotenbahnhoefen
        hubs = {k for k in nb if len(nb[k]) >= 3} | set(self.positions) & set(self.nodes)
        if not hubs:   # einzelne Linie(n): ein Ende als Anker
            hubs = {max(self.nodes, key=lambda k: (len(nb[k]) == 1, len(lines_at[k])))}
        chains, seen = [], set()
        for h in sorted(hubs):
            for x in sorted(nb[h]):
                ch, prev = [h, x], h
                while x not in hubs and len(nb[x]) == 2:
                    prev, x = x, next(y for y in nb[x] if y != prev)
                    ch.append(x)
                key = frozenset(zip(ch, ch[1:]))
                if key not in seen:
                    seen.add(key)
                    chains.append(ch)
        inner = [c for c in chains if c[-1] in hubs]
        leaves = [c for c in chains if c[-1] not in hubs]

        pos: dict[str, tuple] = {}
        fixed = {k: tuple(map(int, v)) for k, v in self.positions.items() if k in self.nodes}
        H = sorted(hubs)
        # Soll-Laenge je Kette: Anzahl Abstaende x S (+ Platz fuer grosse Knoten)
        ideal: dict[tuple, float] = {}
        for c in inner:
            a, b = sorted((c[0], c[-1]))
            if a == b:
                continue
            L = (len(c) - 1) * S + (size(a)[1] + size(b)[1]) / 4
            ideal[(a, b)] = max(ideal.get((a, b), 0), L)
        # Express-Abschnitte (ohne Zwischenhalt) nicht kuerzer als die Geografie hergibt
        chain_r = sorted(L / max(0.3, math.dist(geo[a], geo[b])) for (a, b), L in ideal.items()
                         if L > 1.5 * S)
        kg = chain_r[len(chain_r) // 2] if chain_r else 2 * S
        for (a, b) in ideal:
            ideal[(a, b)] = max(ideal[(a, b)], 0.7 * kg * math.dist(geo[a], geo[b]))
        # Graphabstaende zwischen allen Knotenbahnhoefen (Dijkstra)
        adj: dict[str, list] = {h: [] for h in H}
        for (a, b), L in ideal.items():
            adj[a].append((b, L)); adj[b].append((a, L))
        D = {}
        for h in H:
            dist, todo = {h: 0.0}, [(0.0, h)]
            while todo:
                todo.sort(); d, u = todo.pop(0)
                if d > dist.get(u, 1e18):
                    continue
                for v, L in adj[u]:
                    if d + L < dist.get(v, 1e18):
                        dist[v] = d + L; todo.append((d + L, v))
            D[h] = dist
        for (a, b), L in ideal.items():   # jede Kette will ihre eigene Laenge
            D[a][b] = D[b][a] = max(D[a].get(b, 0), L)
        # Start: Geografie, Massstab = Median der Soll/Ist-Verhaeltnisse
        ratios = sorted(L / max(0.3, math.dist(geo[a], geo[b])) for (a, b), L in ideal.items())
        k0 = ratios[len(ratios) // 2] if ratios else self.upk * 2
        P = {h: list(fixed.get(h, (geo[h][0] * k0, geo[h][1] * k0))) for h in H}
        far = max([d for h in H for d in D[h].values()] or [S])
        for h in H:   # nicht verbundene Teile: geografischer Abstand
            for g in H:
                D[h].setdefault(g, math.dist(geo[h], geo[g]) * k0 or far)

        def nearest_dir(vx, vy):
            ang = math.atan2(vy, vx) / (math.pi / 4)
            o = min(range(8), key=lambda o: min((o - ang) % 8, (ang - o) % 8) + 0.25 * (o % 2))
            return [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)][o]

        # Stress-Layout (SMACOF) mit Zug zu 0/45/90 Grad auf den Ketten
        for it in range(400):
            new = {}
            for i in H:
                if i in fixed:
                    new[i] = P[i]; continue
                sx = sy = sw = 0.0
                for j in H:
                    if j == i:
                        continue
                    d = D[i][j] or S
                    w = d ** -2 * (5 if (min(i, j), max(i, j)) in ideal else 1)
                    dx, dy = P[i][0] - P[j][0], P[i][1] - P[j][1]
                    r = math.hypot(dx, dy) or 1e-6
                    sx += w * (P[j][0] + d * dx / r); sy += w * (P[j][1] + d * dy / r); sw += w
                new[i] = [sx / sw, sy / sw] if sw else P[i]
            P = new
            if it > 100:   # oktilinear ausrichten
                alpha = 0.3
                for (a, b), L in ideal.items():
                    vx, vy = P[b][0] - P[a][0], P[b][1] - P[a][1]
                    r = math.hypot(vx, vy) or 1e-6
                    ux, uy = nearest_dir(vx, vy)
                    n = math.hypot(ux, uy)
                    tx, ty = ux / n * r, uy / n * r
                    cx, cy = (tx - vx) * alpha / 2, (ty - vy) * alpha / 2
                    if a not in fixed:
                        P[a] = [P[a][0] - cx, P[a][1] - cy]
                    if b not in fixed:
                        P[b] = [P[b][0] + cx, P[b][1] + cy]
        for h in H:
            pos[h] = tuple(P[h])
        # Knotenbahnhoefe auseinanderschieben, wo sie sich ueberlappen
        for _ in range(200):
            moved = False
            for i, a in enumerate(H):
                for b in H[i + 1:]:
                    (ax, ay), (bx, by) = pos[a], pos[b]
                    (aw, ah), (bw, bh) = size(a), size(b)
                    ox = min(ax + aw, bx + bw) - max(ax, bx) + 2 * GRID
                    oy = min(ay + ah, by + bh) - max(ay, by) + 2 * GRID
                    if ox > 0 and oy > 0:
                        dx, dy = (bx - ax) or 0.1, (by - ay) or 0.1
                        if ox / abs(dx) < oy / abs(dy):
                            mx, my = math.copysign(ox / 2, dx), 0
                        else:
                            mx, my = 0, math.copysign(oy / 2, dy)
                        if a not in fixed:
                            pos[a] = (ax - mx, ay - my)
                        if b not in fixed:
                            pos[b] = (bx + mx, by + my)
                        moved = True
            if not moved:
                break
        pos = {k: (snap(x), snap(y)) for k, (x, y) in pos.items()}
        used: dict[str, set] = {k: set() for k in self.nodes}

        def octant(dx, dy):
            return round(math.atan2(dy, dx) / (math.pi / 4)) % 8

        def center(k):
            w, hh = size(k)
            return pos[k][0] + w / 2, pos[k][1] + hh / 2

        # Ketten zwischen zwei Knoten: gleichmaessig auf der Geraden; wo das kollidiert
        # oder kreuzt, seitlich ausgebeult (Platzierung kurze Ketten zuerst)
        def cross(p1, p2, p3, p4):
            def o(a, b, c):
                v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                return (v > 0) - (v < 0)
            if {p1, p2} & {p3, p4}:
                return False
            return o(p1, p2, p3) != o(p1, p2, p4) and o(p3, p4, p1) != o(p3, p4, p2)

        def segs():
            out = set()
            for a in nb:
                for b in nb[a]:
                    if a < b and a in pos and b in pos:
                        out.add((pos[a], pos[b]))
            return out

        def free(k, xy):
            w, hgt = size(k)
            for j, (px, py) in pos.items():
                if j == k:
                    continue
                pw, ph = size(j)
                if xy[0] < px + pw + GRID and px < xy[0] + w + GRID and \
                        xy[1] < py + ph + GRID and py < xy[1] + hgt + GRID:
                    return False
            return True

        def badness(ch, pts):
            sc = sum(not free(k, p) for k, p in zip(ch[1:], pts) if k not in pos)
            line = [pos[ch[0]]] + pts + ([pos[ch[-1]]] if ch[-1] in pos and len(pts) < len(ch) - 1 else [])
            ss = segs()
            sc += sum(cross(a, b, c, d) for a, b in zip(line, line[1:]) for c, d in ss)
            return sc

        for c in sorted(inner, key=len):
            if len(c) <= 2 or all(k in pos for k in c[1:-1]):
                continue
            (x0, y0), (x1, y1) = center(c[0]), center(c[-1])
            n = len(c) - 1
            r = math.hypot(x1 - x0, y1 - y0) or 1
            px, py = -(y1 - y0) / r, (x1 - x0) / r
            unit = 3 * GRID + max(size(x)[1] for x in c[1:-1])
            best = None
            for m in (0, 1, -1, 2, -2, 3, -3):
                pts = []
                for i, k in enumerate(c[1:-1], 1):
                    t = i / n
                    # Ausbeulung: an den Enden halb, in der Mitte voll
                    bump = m * unit * min(1.0, 2 * min(t, 1 - t) + 0.5)
                    w, hh = size(k)
                    pts.append((snap(x0 + (x1 - x0) * t + px * bump - w / 2),
                                snap(y0 + (y1 - y0) * t + py * bump - hh / 2)))
                sc = badness(c[:-1] + [c[-1]], pts) + 0.3 * abs(m)
                if best is None or sc < best[0]:
                    best = (sc, pts)
                if sc == 0:
                    break
            for k, p in zip(c[1:-1], best[1]):
                pos.setdefault(k, fixed.get(k, p))
            used[c[0]].add(octant(x1 - x0, y1 - y0)); used[c[-1]].add(octant(x0 - x1, y0 - y1))
        k_upk = k0

        DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
        gap = max(GRID, S - 3 * GRID)

        def walk(h, ch, o):
            dx, dy = DIRS[o]
            f = 0.75 if dx and dy else 1
            pts, (x, y), prev = [], pos[h], h
            for k in ch[1:]:
                (w0, h0), (w1, h1) = size(prev), size(k)
                x += 0 if not dx else (w0 + gap) * f if dx > 0 else -(w1 + gap) * f
                y += 0 if not dy else (h0 + gap) * f if dy > 0 else -(h1 + gap) * f
                pts.append((snap(x), snap(y)))
                prev = k
            return pts

        for ch in sorted(leaves, key=lambda c: -len(c)):   # offene Aeste als Perlschnur
            h, end = ch[0], ch[-1]
            gx, gy = geo[end][0] - geo[h][0], geo[end][1] - geo[h][1]
            ang = math.atan2(gy, gx) / (math.pi / 4) if (gx or gy) else 0
            cands = sorted(range(8), key=lambda o: min((o - ang) % 8, (ang - o) % 8) + 0.4 * (o % 2))
            best = None
            for o in cands:
                pts = walk(h, ch, o)
                score = sum(not free(k, p) for k, p in zip(ch[1:], pts))
                line = [pos[h]] + pts
                ss = segs()
                score += sum(cross(a, b, c, d) for a, b in zip(line, line[1:]) for c, d in ss)
                if best is None or score < best[0]:
                    best = (score, o, pts)
                if score == 0:
                    break
            _, o, pts = best or (0, cands[0], walk(h, ch, cands[0]))
            for k, p in zip(ch[1:], pts):
                pos.setdefault(k, fixed.get(k, p))
            used[h].add(o)
        # letzte Kontrolle: ueberlappende Knoten auseinanderschieben (Zwischenhalte zuerst)
        keys = list(pos)
        for _ in range(100):
            moved = False
            for i, a in enumerate(keys):
                for b in keys[i + 1:]:
                    (ax, ay), (bx, by) = pos[a], pos[b]
                    (aw, ah), (bw, bh) = size(a), size(b)
                    ox = min(ax + aw, bx + bw) - max(ax, bx) + GRID
                    oy = min(ay + ah, by + bh) - max(ay, by) + GRID
                    if ox > 0 and oy > 0:
                        wa = 0 if a in fixed else (0.2 if a in hubs else 1)
                        wb = 0 if b in fixed else (0.2 if b in hubs else 1)
                        if wa + wb == 0:
                            continue
                        dx, dy = (bx - ax) or 1, (by - ay) or 1
                        if ox <= oy:
                            m, ax_ = math.copysign(ox, dx), 0
                        else:
                            m, ax_ = math.copysign(oy, dy), 1
                        fa, fb = wa / (wa + wb), wb / (wa + wb)
                        if ax_ == 0:
                            pos[a] = (snap(ax - m * fa), ay); pos[b] = (snap(bx + m * fb), by)
                        else:
                            pos[a] = (ax, snap(ay - m * fa)); pos[b] = (bx, snap(by + m * fb))
                        moved = True
            if not moved:
                break
        for k, n in self.nodes.items():
            n["positionX"], n["positionY"] = map(int, pos.get(k, (snap(geo[k][0] * k_upk), snap(geo[k][1] * k_upk))))

    # ---------- Linien ----------
    def trainrun(self, spec: dict) -> int:
        stops = spec["stops"]
        if len(stops) < 2:
            raise ValueError(f"{spec.get('name')}: mindestens 2 Halte noetig")
        tid = self._next("trainrun")
        self.trainruns.append({
            "id": tid, "name": spec.get("name", f"Linie {tid}"),
            "categoryId": self._meta_id("trainrunCategories", spec.get("category", "S")),
            "frequencyId": self._meta_id("trainrunFrequencies", spec.get("frequency", "60")),
            "trainrunTimeCategoryId": self._meta_id("trainrunTimeCategories", spec.get("timeCategory", "7/24")),
            "labelIds": [], "direction": spec.get("direction", "round_trip"),
        })
        nodes = [self.node(s["at"], s.get("name")) for s in stops]
        for a, b in zip(nodes, nodes[1:]):
            if a is b:
                raise ValueError(f"{spec.get('name')}: Knoten {a['betriebspunktName']} doppelt hintereinander")

        fwd_arr = [s.get("arr") for s in stops]
        fwd_dep = [s.get("dep") for s in stops]
        for i in range(len(stops)):          # fehlende Werte auffuellen
            if fwd_dep[i] is None:
                fwd_dep[i] = fwd_arr[i]
            if fwd_arr[i] is None:
                fwd_arr[i] = fwd_dep[i]
        if any(v is None for v in fwd_dep[:-1]) or fwd_arr[-1] is None:
            raise ValueError(f"{spec.get('name')}: Zeiten unvollstaendig")
        # Monotonie (Mitternacht/Stundenwechsel in der Spec vergessen?)
        for i in range(1, len(stops)):
            while fwd_arr[i] < fwd_dep[i - 1]:
                fwd_arr[i] += 60
            while fwd_dep[i] < fwd_arr[i]:
                fwd_dep[i] += 60

        back = spec.get("back")
        if back:
            bmap = {}
            for s in back:
                bmap[s["at"].upper()] = (s.get("arr"), s.get("dep"))
            keys = [s["at"].upper() for s in stops]
            missing = [k for k in keys if k not in bmap]
            if missing:
                raise ValueError(f"{spec.get('name')}: Rueckfahrt fehlt an {missing}")
            b_arr = [bmap[k][0] for k in keys]
            b_dep = [bmap[k][1] for k in keys]
            for i in range(len(keys)):
                if b_dep[i] is None:
                    b_dep[i] = b_arr[i]
                if b_arr[i] is None:
                    b_arr[i] = b_dep[i]
            # rueckwaerts monoton machen (Fahrt laeuft von hinten nach vorne)
            for i in range(len(keys) - 2, -1, -1):
                while b_arr[i] < b_dep[i + 1]:
                    b_arr[i] += 60
                while b_dep[i] < b_arr[i]:
                    b_dep[i] += 60
        else:
            C = 60 * math.ceil((max(fwd_arr + fwd_dep) + 1) / 60)
            b_arr = [C - d for d in fwd_dep]
            b_dep = [C - a for a in fwd_arr]

        sec_ids = []
        for i in range(len(stops) - 1):
            src, tgt = nodes[i], nodes[i + 1]
            sid = self._next("section")
            sp, tp = self._next("port"), self._next("port")
            s_dep, t_arr = fwd_dep[i], fwd_arr[i + 1]
            t_dep, s_arr = b_dep[i + 1], b_arr[i]
            sym_s = (s_arr % 60) == (-s_dep) % 60
            sym_t = (t_dep % 60) == (-t_arr) % 60
            self.sections.append({
                "id": sid,
                "sourceNodeId": src["id"], "sourcePortId": sp,
                "targetNodeId": tgt["id"], "targetPortId": tp,
                "sourceDeparture": _tm(s_dep), "sourceArrival": _tm(s_arr),
                "targetDeparture": _tm(t_dep), "targetArrival": _tm(t_arr),
                "travelTime": _tm(t_arr - s_dep, lock=True),
                "backwardTravelTime": _tm(s_arr - t_dep, lock=True),
                "sourceSymmetry": sym_s, "targetSymmetry": sym_t,
                "numberOfStops": int(stops[i + 1].get("skipped", 0)),
                "trainrunId": tid, "resourceId": 0,
                "specificTrainrunSectionFrequencyId": None,
                "path": {"path": [], "textPositions": {}}, "warnings": None,
            })
            # travelTime.time ist eine Dauer, keine Minute-in-der-Stunde
            for k in ("travelTime", "backwardTravelTime"):
                v = self.sections[-1][k]["consecutiveTime"]
                self.sections[-1][k]["time"] = v
                self.sections[-1][k]["consecutiveTime"] = v
            src["ports"].append({"id": sp, "trainrunSectionId": sid, "positionIndex": 0,
                                 "positionAlignment": TOP, "_other": tgt})
            tgt["ports"].append({"id": tp, "trainrunSectionId": sid, "positionIndex": 0,
                                 "positionAlignment": TOP, "_other": src})
            sec_ids.append((sid, sp, tp))
        for i in range(1, len(stops) - 1):
            self.nodes[stops[i]["at"].upper()]["transitions"].append({
                "id": self._next("transition"),
                "port1Id": sec_ids[i - 1][2], "port2Id": sec_ids[i][1],
                "isNonStopTransit": bool(stops[i].get("pass")),
            })
        return tid

    # ---------- Geometrie ----------
    def _finish_ports(self):
        for n in self.nodes.values():
            for p in n["ports"]:
                o = p["_other"]
                p["positionAlignment"] = align(o["positionX"] - n["positionX"],
                                               o["positionY"] - n["positionY"])
            for side in (TOP, BOTTOM, LEFT, RIGHT):
                ps = [p for p in n["ports"] if p["positionAlignment"] == side]
                key = (lambda p: (p["_other"]["positionX"], p["_other"]["positionY"])) \
                    if side in (TOP, BOTTOM) else \
                    (lambda p: (p["_other"]["positionY"], p["_other"]["positionX"]))
                for i, p in enumerate(sorted(ps, key=key)):
                    p["positionIndex"] = i

    def _port_xy(self, n: dict, p: dict) -> tuple[float, float]:
        nh = max(2 * GRID, max([q["positionIndex"] + 1 for q in n["ports"]
                                if q["positionAlignment"] in (LEFT, RIGHT)] or [0]) * GRID + TEXT_H)
        nw = max(3 * GRID, max([q["positionIndex"] + 1 for q in n["ports"]
                                if q["positionAlignment"] in (TOP, BOTTOM)] or [0]) * GRID)
        x, y, a, i = n["positionX"], n["positionY"], p["positionAlignment"], p["positionIndex"]
        if a == LEFT:
            return x, y + TEXT_H + GRID / 2 + i * GRID
        if a == RIGHT:
            return x + nw, y + TEXT_H + GRID / 2 + i * GRID
        if a == TOP:
            return x + GRID / 2 + i * GRID, y
        return x + GRID / 2 + i * GRID, y + nh

    def _paths(self):
        out = {LEFT: (-1, 0), RIGHT: (1, 0), TOP: (0, -1), BOTTOM: (0, 1)}
        nodes_by_id = {n["id"]: n for n in self.nodes.values()}
        for s in self.sections:
            sn, tn = nodes_by_id[s["sourceNodeId"]], nodes_by_id[s["targetNodeId"]]
            sp = next(p for p in sn["ports"] if p["id"] == s["sourcePortId"])
            tp = next(p for p in tn["ports"] if p["id"] == s["targetPortId"])
            p0, p3 = self._port_xy(sn, sp), self._port_xy(tn, tp)
            d0, d3 = out[sp["positionAlignment"]], out[tp["positionAlignment"]]
            p1 = (p0[0] + 2 * GRID * d0[0], p0[1] + 2 * GRID * d0[1])
            p2 = (p3[0] + 2 * GRID * d3[0], p3[1] + 2 * GRID * d3[1])
            mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            s["path"] = {
                "path": [{"x": p[0], "y": p[1]} for p in (p0, p1, p2, p3)],
                "textPositions": {
                    "0": {"x": p0[0] + 18 * d0[0], "y": p0[1] + 12},
                    "1": {"x": p0[0] + 46 * d0[0], "y": p0[1] - 12},
                    "2": {"x": p3[0] + 18 * d3[0], "y": p3[1] - 12},
                    "3": {"x": p3[0] + 46 * d3[0], "y": p3[1] + 12},
                    "4": {"x": mid[0], "y": mid[1] - 12}, "5": {"x": mid[0], "y": mid[1] - 12},
                    "6": {"x": mid[0], "y": mid[1] + 12}, "7": {"x": mid[0], "y": mid[1] + 12},
                },
            }

    def to_json(self) -> dict:
        self._place_nodes()
        self._finish_ports()
        self._paths()
        nodes = []
        for n in self.nodes.values():
            n = dict(n)
            n["ports"] = [{k: v for k, v in p.items() if k != "_other"} for p in n["ports"]]
            n["perronkanten"] = max(2, min(20, len({p["trainrunSectionId"] for p in n["ports"]})))
            nodes.append(n)
        return {
            "nodes": nodes, "trainrunSections": self.sections, "trainruns": self.trainruns,
            "resources": self.resources, "metadata": self.meta, "freeFloatingTexts": [],
            "labels": [], "labelGroups": [], "filterData": {"filterSettings": []},
        }


def build(spec: dict, db: StationDB | None, upk: float = 80, metadata: dict | None = None,
          positions: dict | None = None, layout: str = "geo",
          spacing: float = 8 * GRID) -> tuple[dict, list[str]]:
    pos = dict(spec.get("positions") or {})
    pos.update(positions or {})
    b = Builder(db, metadata, upk, pos, layout=layout, spacing=spacing)
    for tr in spec["trainruns"]:
        if tr.get("skip"):
            continue
        b.trainrun(tr)
    return b.to_json(), b.warnings


def positions_from(files: list[Path]) -> dict:
    """Knotenpositionen aus (von Hand verschobenen) NGE-Exporten sammeln."""
    pos = {}
    for f in files:
        d = json.loads(Path(f).read_text())
        for n in d["nodes"]:
            pos[n["betriebspunktName"].upper()] = [n["positionX"], n["positionY"]]
    return pos
