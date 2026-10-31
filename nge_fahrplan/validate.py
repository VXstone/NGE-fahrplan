"""Pruefungen vor der Auslieferung (Cookbook Abschnitt 6) + ein paar mehr.

Ein Fehler hier bedeutet fast immer: NGE laedt die Datei nicht (leerer Bildschirm).
"""
from __future__ import annotations

from collections import Counter


def validate(d: dict) -> list[str]:
    err: list[str] = []
    for key in ("nodes", "trainrunSections", "trainruns", "resources", "metadata"):
        if key not in d:
            err.append(f"Top-Level-Key fehlt: {key}")
    if err:
        return err
    nodes, secs, trs = d["nodes"], d["trainrunSections"], d["trainruns"]
    sec_ids = {s["id"] for s in secs}
    tr_ids = {t["id"] for t in trs}
    node_by_id = {n["id"]: n for n in nodes}
    res_ids = {r["id"] for r in d["resources"]}

    for name, ids in (("nodes", [n["id"] for n in nodes]), ("trainrunSections", [s["id"] for s in secs]),
                      ("trainruns", [t["id"] for t in trs]),
                      ("ports", [p["id"] for n in nodes for p in n["ports"]]),
                      ("transitions", [t["id"] for n in nodes for t in n["transitions"]]),
                      ("resources", [r["id"] for r in d["resources"]])):
        dup = [i for i, c in Counter(ids).items() if c > 1]
        if dup:
            err.append(f"doppelte {name}-IDs: {dup[:10]}")
    dupname = [k for k, c in Counter(n["betriebspunktName"] for n in nodes).items() if c > 1]
    if dupname:
        err.append(f"doppelte betriebspunktName: {dupname}")

    for n in nodes:
        pids = {p["id"] for p in n["ports"]}
        for p in n["ports"]:
            if p["trainrunSectionId"] not in sec_ids:
                err.append(f"{n['betriebspunktName']}: Port {p['id']} -> fehlende Section {p['trainrunSectionId']}")
            if p.get("positionAlignment") not in (0, 1, 2, 3):
                err.append(f"{n['betriebspunktName']}: Port {p['id']} ungueltiges positionAlignment")
        for t in n["transitions"]:
            if t["port1Id"] not in pids or t["port2Id"] not in pids:
                err.append(f"{n['betriebspunktName']}: Transition {t['id']} -> fehlender Port")
        if n.get("resourceId") not in res_ids:
            err.append(f"{n['betriebspunktName']}: resourceId {n.get('resourceId')} fehlt in resources")

    for s in secs:
        if s["trainrunId"] not in tr_ids:
            err.append(f"Section {s['id']}: Trainrun {s['trainrunId']} fehlt")
        for end in ("source", "target"):
            n = node_by_id.get(s[f"{end}NodeId"])
            if n is None:
                err.append(f"Section {s['id']}: {end}Node fehlt")
                continue
            ports = [p for p in n["ports"] if p["id"] == s[f"{end}PortId"]]
            if not ports or ports[0]["trainrunSectionId"] != s["id"]:
                err.append(f"Section {s['id']}: {end}Port {s[f'{end}PortId']} nicht an {n['betriebspunktName']}")
        for k in ("travelTime", "backwardTravelTime", "sourceDeparture", "sourceArrival",
                  "targetDeparture", "targetArrival"):
            if k not in s:
                err.append(f"Section {s['id']}: {k} fehlt")
            elif k.endswith("TravelTime") or k == "travelTime":
                if s[k]["time"] < 0:
                    err.append(f"Section {s['id']}: {k} negativ ({s[k]['time']})")
            elif not 0 <= s[k]["time"] <= 59:
                err.append(f"Section {s['id']}: {k}.time ausserhalb 0..59")

    meta = d["metadata"]
    for t in trs:
        for fld, table in (("categoryId", "trainrunCategories"), ("frequencyId", "trainrunFrequencies"),
                           ("trainrunTimeCategoryId", "trainrunTimeCategories")):
            if t.get(fld) not in {e["id"] for e in meta.get(table, [])}:
                err.append(f"Trainrun {t['name']}: {fld}={t.get(fld)} nicht in metadata.{table}")
        if t.get("direction") not in ("round_trip", "one_way"):
            err.append(f"Trainrun {t['name']}: direction fehlt/ungueltig")
        if not any(s["trainrunId"] == t["id"] for s in secs):
            err.append(f"Trainrun {t['name']}: ohne Sections")
    return err


def departures(d: dict, abbr: str) -> list[str]:
    """Abfahrts-/Ankunftsminuten an einem Knoten – zum Abgleich mit der SMA-Netzgrafik."""
    node = next(n for n in d["nodes"] if n["betriebspunktName"].upper() == abbr.upper())
    trs = {t["id"]: t["name"] for t in d["trainruns"]}
    nb = {n["id"]: n["betriebspunktName"] for n in d["nodes"]}
    out = []
    for s in d["trainrunSections"]:
        if s["sourceNodeId"] == node["id"]:
            out.append(f"{trs[s['trainrunId']]:24} -> {nb[s['targetNodeId']]:6} ab {s['sourceDeparture']['time']:02d}  an {s['sourceArrival']['time']:02d}")
        if s["targetNodeId"] == node["id"]:
            out.append(f"{trs[s['trainrunId']]:24} -> {nb[s['sourceNodeId']]:6} ab {s['targetDeparture']['time']:02d}  an {s['targetArrival']['time']:02d}")
    return sorted(out)
