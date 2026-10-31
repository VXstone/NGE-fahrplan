"""HRDF 5.40 (opentransportdata.swiss) – gezieltes Lesen ohne Entpacken.

FPLAN ist mehrere GB gross und wird zeilenweise aus dem ZIP gestreamt. Pro Fahrt
(``*Z``-Block) werden nur die Halte an den gewuenschten Stationen behalten,
zusammen mit der Zahl der dazwischen uebersprungenen Halte (-> numberOfStops).

Wichtige Formatdetails (siehe NGE_JSON_Cookbook):
* Datei als UTF-8 dekodieren, *dann* Spalten schneiden (Umlaute!)
* Zeitfeld: Vorzeichen + HHH + MM (3-stellige Stunde, Folgetag = 24..47)
* Negatives Vorzeichen = Durchfahrt / kein Ein- und Aussteigen
* ``*Z`` kann eine Taktfahrt sein (Anzahl + Taktzeit) -> wird expandiert
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterator


class HRDF:
    def __init__(self, zip_path: Path):
        self.path = Path(zip_path)
        self.zip = zipfile.ZipFile(self.path)
        self.names = {n.rsplit("/", 1)[-1].upper(): n for n in self.zip.namelist()}
        self.start, self.end = self._eckdaten()
        self._bitfields: dict[str, str] | None = None
        self._lines: dict[str, str] | None = None

    # ---------- kleine Referenzdateien ----------
    def _text(self, name: str) -> Iterator[str]:
        with self.zip.open(self.names[name]) as f:
            yield from io.TextIOWrapper(f, encoding="utf-8", errors="replace")

    def _eckdaten(self) -> tuple[dt.date, dt.date]:
        dates = []
        for line in self._text("ECKDATEN"):
            s = line.strip()[:10]
            try:
                dates.append(dt.datetime.strptime(s, "%d.%m.%Y").date())
            except ValueError:
                pass
            if len(dates) == 2:
                break
        return dates[0], dates[1]

    @property
    def bitfields(self) -> dict[str, str]:
        if self._bitfields is None:
            self._bitfields = {}
            for line in self._text("BITFELD"):
                p = line.split()
                if len(p) >= 2:
                    self._bitfields[p[0]] = p[1]
        return self._bitfields

    @property
    def line_names(self) -> dict[str, str]:
        """LINIE: ``0000001 K 66`` -> {'0000001': '66'}"""
        if self._lines is None:
            self._lines = {}
            if "LINIE" in self.names:
                for line in self._text("LINIE"):
                    p = line.split(None, 2)
                    if len(p) == 3 and p[1] == "K":
                        self._lines[p[0]] = p[2].strip()
        return self._lines

    def runs_on(self, bitfield: str | None, day: dt.date) -> bool:
        """Verkehrstag-Pruefung. Bit 0 (MSB des ersten Hex-Zeichens) = Fahrplanstart.
        Bitfeld 000000 / leer = taeglich."""
        if not bitfield or int(bitfield) == 0:
            return True
        hexs = self.bitfields.get(bitfield)
        if hexs is None:
            return True
        i = (day - self.start).days
        if i < 0 or i >= len(hexs) * 4:
            return False
        return bool(int(hexs[i // 4], 16) & (8 >> (i % 4)))

    # ---------- FPLAN ----------
    def _fplan_lines(self) -> Iterator[str]:
        """Streamt FPLAN; nutzt ``unzip -p`` wenn vorhanden (2-3x schneller)."""
        member = self.names["FPLAN"]
        if shutil.which("unzip"):
            p = subprocess.Popen(["unzip", "-p", str(self.path), member], stdout=subprocess.PIPE)
            with io.TextIOWrapper(p.stdout, encoding="utf-8", errors="replace") as f:
                yield from f
            p.wait()
        else:
            yield from self._text("FPLAN")

    def trips(self, station_numbers: set[int], day: dt.date | None = None,
              categories: set[str] | None = None, min_stops: int = 2,
              verbose: bool = False) -> Iterator[dict]:
        """Alle Fahrten mit mindestens ``min_stops`` Halten in ``station_numbers``."""
        cur: dict | None = None
        n_total = n_kept = 0

        def finish(t):
            nonlocal n_kept
            if t is None:
                return []
            kept = t["stops"]
            if sum(1 for s in kept if not s["pass"]) < min_stops:
                return []
            if categories and t["cat"] not in categories:
                return []
            if day is not None and not self.runs_on(t["bitfield"], day):
                return []
            ln = t["line"]
            if ln.startswith("#"):
                t["line"] = self.line_names.get(ln[1:].strip().zfill(7), ln)
            out = [t]
            # Taktfahrt expandieren
            if t["takt_n"] and t["takt_t"]:
                for k in range(1, t["takt_n"] + 1):
                    d = k * t["takt_t"]
                    c = json.loads(json.dumps(t))
                    c["fnr"] = f"{t['fnr']}+{k}"
                    for s in c["stops"]:
                        s["arr"] = None if s["arr"] is None else s["arr"] + d
                        s["dep"] = None if s["dep"] is None else s["dep"] + d
                    out.append(c)
            for o in out:
                o.pop("takt_n"), o.pop("takt_t")
            n_kept += len(out)
            return out

        for raw in self._fplan_lines():
            line = raw.rstrip("\r\n")
            if line.startswith("*Z"):
                yield from finish(cur)
                n_total += 1
                if verbose and n_total % 200000 == 0:
                    print(f"  {n_total} Fahrten gelesen, {n_kept} behalten", file=sys.stderr)
                tn, tt = line[22:25].strip(), line[26:29].strip()
                cur = {"fnr": line[3:9].strip(), "admin": line[10:16].strip(),
                       "cat": "", "line": "", "bitfield": None,
                       "takt_n": int(tn) if tn.isdigit() else 0,
                       "takt_t": int(tt) if tt.isdigit() else 0,
                       "stops": [], "_skip": 0}
            elif cur is None:
                continue
            elif line.startswith("*G"):
                if not cur["cat"]:
                    p = line.split()
                    cur["cat"] = p[1] if len(p) > 1 else ""
            elif line.startswith("*L"):
                if not cur["line"]:
                    p = line.split()
                    cur["line"] = p[1] if len(p) > 1 else ""
            elif line.startswith("*A VE"):
                if cur["bitfield"] is None:
                    p = line.split()
                    cur["bitfield"] = p[-1] if len(p) >= 3 and p[-1].isdigit() else None
            elif line[:7].isdigit():
                num = int(line[:7])
                arr_f, dep_f = line[29:35], line[36:42]
                arr, dep = parse_time(arr_f), parse_time(dep_f)
                fields = [x.strip() for x in (arr_f, dep_f) if x.strip()]
                # Durchfahrt: alle vorhandenen Zeiten negativ (kein Ein-/Aussteigen)
                is_pass = bool(fields) and all(x.startswith("-") for x in fields)
                if num in station_numbers:
                    cur["stops"].append({"num": num, "arr": arr, "dep": dep,
                                         "pass": bool(is_pass), "skipped": cur["_skip"]})
                    cur["_skip"] = 0
                elif cur["stops"] and not is_pass:
                    cur["_skip"] += 1
        yield from finish(cur)
        if verbose:
            print(f"  fertig: {n_total} Fahrten gelesen, {n_kept} behalten", file=sys.stderr)


def parse_time(field: str) -> int | None:
    """``-00813`` / `` 02405`` -> Minuten seit Mitternacht (Folgetag > 1440)."""
    f = field.strip()
    if not f:
        return None
    d = f.lstrip("+- ")
    if len(d) < 3 or not d.isdigit():
        return None
    return int(d[:-2]) * 60 + int(d[-2:])


def extract(hrdf_zip: Path, station_numbers: list[int], out: Path,
            day: dt.date | None = None, categories: set[str] | None = None,
            verbose: bool = False) -> int:
    h = HRDF(hrdf_zip)
    trips = []
    for t in h.trips(set(station_numbers), day, categories, verbose=verbose):
        t.pop("_skip", None)
        trips.append(t)
    meta = {"hrdf": Path(hrdf_zip).name, "period": [str(h.start), str(h.end)],
            "day": str(day) if day else None, "stations": list(station_numbers)}   # Reihenfolge = Linienrichtung
    save_trips({"meta": meta, "trips": trips}, out)
    print(f"{len(trips)} Fahrten -> {out}", file=sys.stderr)
    return len(trips)


def load_trips(path: Path) -> dict:
    """trips.json oder trips.json.gz lesen."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def save_trips(data: dict, out: Path) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if out.suffix == ".gz" else open
    with opener(out, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


def subset(data: dict, station_numbers: list[int], categories: set[str] | None = None,
           min_stops: int = 2) -> dict:
    """Region aus einer vorbereiteten Fahrtendatei (z.B. trips_bahn.json.gz) schneiden.
    Weggelassene Halte werden zu ``skipped`` des naechsten behaltenen Halts addiert."""
    keep = set(station_numbers)
    out = []
    for t in data["trips"]:
        if categories and t["cat"] not in categories:
            continue
        stops, acc = [], 0
        for s in t["stops"]:
            if s["num"] in keep:
                stops.append(dict(s, skipped=(acc + s.get("skipped", 0)) if stops else 0))
                acc = 0
            else:
                acc += s.get("skipped", 0) + (0 if s.get("pass") else 1)
        if sum(1 for s in stops if not s["pass"]) >= min_stops:
            out.append(dict(t, stops=stops))
    meta = dict(data.get("meta", {}), stations=list(station_numbers))
    return {"meta": meta, "trips": out}
