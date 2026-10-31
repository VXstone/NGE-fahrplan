"""Von HRDF-Einzelfahrten zu Taktlinien (Spec-Entwurf).

Tausende Fahrten werden zu wenigen Linien verdichtet:

1. Gruppe = (Kategorie, Linie, Haltefolge in der Region, Durchfahrten)
2. In der Gruppe: Signatur = (Abfahrtsminute mod 60, relative Fahrzeiten).
   Die haeufigste Signatur ist die Regelstundenfahrt.
3. Takt aus den abgedeckten Stunden 6–21 Uhr:
   >= 12 Stunden -> 60', nur gerade -> 120, nur ungerade -> 120+,
   gehaeuft 6–8/16–19 Uhr -> HVZ, sonst "zeitweise".
   Gleiche Signatur um 30/20/15 Minuten versetzt -> 30'/20'/15'-Takt.
4. Gegenrichtung = Gruppe mit umgekehrter Haltefolge; ihre haeufigste Signatur
   liefert die echten Rueckfahrzeiten (asymmetrisch moeglich). Fehlt sie,
   wird die Linie als ``one_way`` angelegt.

Das Ergebnis ist eine von Hand bearbeitbare ``spec.json`` – bewusst ein
Entwurf: Varianten, Regionsrand und seltene Fahrten gehoeren gesichtet.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .didok import StationDB
from .hrdf import load_trips

# HRDF-Gattung -> NGE-Kategorie (shortName in den Standard-Metadaten)
CATEGORY_MAP = {
    "EC": "EC", "ICE": "EC", "TGV": "EC", "RJ": "EC", "RJX": "EC", "EN": "EC", "NJ": "EC",
    "EXT": "EC", "FLX": "EC",
    "IC": "IC", "ICN": "IC",
    "IR": "IR", "PE": "IR",
    "RE": "RE", "TER": "RE",
    "S": "S", "SN": "S", "R": "S", "RB": "S", "SL": "S",
}
RAIL = set(CATEGORY_MAP) | {"CC", "PB"}  # CC/PB = Zahnrad, Panoramazug -> S

DAY_HOURS = range(6, 22)


def _sig(trip: dict) -> tuple:
    st = trip["stops"]
    t0 = st[0]["dep"] if st[0]["dep"] is not None else st[0]["arr"]
    rel = []
    for s in st:
        rel.append((None if s["arr"] is None else s["arr"] - t0,
                    None if s["dep"] is None else s["dep"] - t0))
    rel[0] = (None, rel[0][1])
    rel[-1] = (rel[-1][0], None)
    return t0 % 60, tuple(rel), t0 // 60


def _frequency(hours: set[int]) -> tuple[str, str]:
    """(frequency shortName, timeCategory shortName)"""
    day = {h % 24 for h in hours} & set(DAY_HOURS)
    if len(day) >= 12:
        return "60", "7/24"
    if day and len(day) >= 6 and all(h % 2 == 0 for h in day):
        return "120", "7/24"
    if day and len(day) >= 6 and all(h % 2 == 1 for h in day):
        return "120+", "7/24"
    hvz = {6, 7, 8, 16, 17, 18, 19}
    if day and len(day & hvz) >= 0.7 * len(day):
        return "60", "HVZ"
    return "60", "zeitweise"


def group_trips(trips: list[dict]) -> dict:
    groups: dict[tuple, list] = defaultdict(list)
    for t in trips:
        if not t["stops"] or len(t["stops"]) < 2:
            continue
        key = (t["cat"], t["line"], tuple(s["num"] for s in t["stops"]),
               tuple(s["pass"] for s in t["stops"]))
        groups[key].append(t)
    return groups


def _patterns(trips: list[dict], merge: bool, include_rare: bool) -> list[dict]:
    """Taktlagen einer Gruppe: [{minute, rel, hours, freq, timecat, trip}]"""
    by_sig: dict[tuple, list] = defaultdict(list)
    for t in trips:
        m, rel, h = _sig(t)
        by_sig[(m, rel)].append((h, t))
    pats = []
    for (m, rel), lst in by_sig.items():
        hours = {h for h, _ in lst}
        freq, tc = _frequency(hours)
        if tc == "zeitweise" and not include_rare and len({h % 24 for h in hours} & set(DAY_HOURS)) < 3:
            continue
        lst.sort(key=lambda x: x[0])
        pats.append({"minute": m, "rel": rel, "hours": sorted(hours), "freq": freq,
                     "timecat": tc, "trip": lst[len(lst) // 2][1], "n": len(lst)})
    pats.sort(key=lambda p: (-len(p["hours"]), p["minute"]))
    if merge:
        pats = _merge_dense(pats)
    return pats


def _merge_dense(pats: list[dict]) -> list[dict]:
    """60'-Lagen mit gleicher Fahrzeit und 30/20/15' Versatz zusammenfassen."""
    out, used = [], set()
    for i, p in enumerate(pats):
        if i in used:
            continue
        merged = False
        if p["freq"] == "60" and p["timecat"] == "7/24":
            for step, name in ((15, "15"), (20, "20"), (30, "30")):
                mins = {(p["minute"] + k * step) % 60 for k in range(60 // step)}
                idx = [j for j, q in enumerate(pats) if j not in used and q["rel"] == p["rel"]
                       and q["freq"] == "60" and q["timecat"] == "7/24" and q["minute"] in mins]
                if len({pats[j]["minute"] for j in idx}) == len(mins):
                    used.update(idx)
                    first = min((pats[j] for j in idx), key=lambda q: q["minute"])
                    out.append(dict(first, freq=name))
                    merged = True
                    break
        if not merged:
            used.add(i)
            out.append(p)
    return out


def _stops_from_trip(trip: dict, db: StationDB) -> list[dict]:
    res = []
    st = trip["stops"]
    for i, s in enumerate(st):
        sta = db.by_num.get(s["num"])
        abbr = (sta.abbr or sta.name) if sta else str(s["num"])   # Ausland oft ohne Kuerzel
        d = {"at": abbr}
        if i > 0 and s["arr"] is not None:
            d["arr"] = s["arr"]
        if i < len(st) - 1 and s["dep"] is not None:
            d["dep"] = s["dep"]
        if s["pass"] and 0 < i < len(st) - 1:
            d["pass"] = True
        if i > 0 and s.get("skipped"):
            d["skipped"] = s["skipped"]
        res.append(d)
    return res


def suggest(trips_file: Path, db: StationDB, out: Path, name: str = "NGE Netz",
            merge: bool = True, include_rare: bool = False,
            rail_only: bool = True) -> dict:
    data = load_trips(trips_file)
    trips = [t for t in data["trips"] if not rail_only or t["cat"] in RAIL]
    groups = group_trips(trips)
    # Linienrichtung: Start an der Station, die in der Stationsliste zuerst kommt
    order = {n: i for i, n in enumerate(data.get("meta", {}).get("stations", []))}

    def rank(k):
        return (order.get(k[2][0], 1e9), order.get(k[2][-1], 1e9))

    done = set()
    trainruns = []
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2])):
        if key in done:
            continue
        cat, line, seq, passes = key
        back_key = (cat, line, tuple(reversed(seq)), tuple(reversed(passes)))
        if back_key in groups and back_key != key and rank(back_key) < rank(key):
            key, back_key = back_key, key
            cat, line, seq, passes = key
        done.add(key)
        back = None
        if back_key in groups and back_key != key:
            done.add(back_key)
            back = _patterns(groups[back_key], merge, include_rare)
        fwd = _patterns(groups[key], merge, include_rare)
        for k, p in enumerate(fwd):
            first = db.by_num.get(seq[0]); last = db.by_num.get(seq[-1])
            label = line if line else cat
            fa = (first.abbr or first.name) if first else seq[0]
            la = (last.abbr or last.name) if last else seq[-1]
            tr = {
                "name": f"{label} {fa}-{la}",
                "category": CATEGORY_MAP.get(cat, "S"),
                "hrdf": {"cat": cat, "line": line, "trips": p["n"], "hours": p["hours"]},
                "frequency": p["freq"],
                "timeCategory": p["timecat"],
                "stops": _stops_from_trip(p["trip"], db),
            }
            # passende Rueckfahrt: gleiche Takt-Art, sonst haeufigste
            if back:
                cand = [q for q in back if q["freq"] == p["freq"] and q["timecat"] == p["timecat"]]
                q = (cand or back)[min(k, len(cand or back) - 1)]
                tr["back"] = _stops_from_trip(q["trip"], db)
                tr["direction"] = "round_trip"
            else:
                tr["direction"] = "one_way"
            if len(fwd) > 1:
                tr["name"] += f" ({p['minute']:02d})"
            trainruns.append(tr)
    spec = {"name": name, "source": data.get("meta", {}), "trainruns": trainruns}
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1))
    return spec


def table(trips_file: Path, db: StationDB, rail_only: bool = True) -> str:
    """Uebersicht fuer die QA (Linie, Halte, Lagen, Takt)."""
    data = load_trips(trips_file)
    trips = [t for t in data["trips"] if not rail_only or t["cat"] in RAIL]
    rows = []
    for (cat, line, seq, _), ts in sorted(group_trips(trips).items(), key=lambda kv: (kv[0][0], kv[0][1])):
        names = [(db.by_num[n].abbr or db.by_num[n].name) if n in db.by_num else str(n) for n in seq]
        pats = _patterns(ts, merge=True, include_rare=True)
        lagen = ", ".join(f":{p['minute']:02d}/{p['freq']}'" + ("" if p["timecat"] == "7/24" else f" {p['timecat']}")
                          for p in pats[:4])
        rows.append(f"{cat:4} {line:6} {len(ts):4} Fahrten  {lagen:28} " + "-".join(names))
    return "\n".join(rows)
