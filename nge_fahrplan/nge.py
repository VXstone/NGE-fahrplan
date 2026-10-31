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
                 upk: float = 80, positions: dict | None = None, min_dist: float = 4 * GRID):
        self.db = db
        self.meta = metadata or default_metadata()
        self.upk = upk
        self.positions = {k.upper(): v for k, v in (positions or {}).items()}
        self.min_dist = min_dist
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
          positions: dict | None = None) -> tuple[dict, list[str]]:
    pos = dict(spec.get("positions") or {})
    pos.update(positions or {})
    b = Builder(db, metadata, upk, pos)
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
