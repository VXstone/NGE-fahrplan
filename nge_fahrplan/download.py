"""Download der offenen Daten (DIDOK/atlas-Dienststellen, HRDF-Fahrplan).

Die Ressourcen-URLs wechseln bei jeder Publikation (HRDF zweimal pro Woche),
darum wird die jeweils neueste Ressource ueber die CKAN-API gesucht.
Ohne Zusatzpakete (nur urllib).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

CKAN = [
    "https://ckan.opendata.swiss/api/3/action/package_show?id={}",
    "https://opendata.swiss/api/3/action/package_show?id={}",
    "https://data.opentransportdata.swiss/api/3/action/package_show?id={}",
]

# Datensatz-Slugs (opendata.swiss bzw. opentransportdata.swiss); {year} wird ersetzt
DATASETS = {
    # atlas v2 (Nachfolger DIDOK) – alle Dienststellen inkl. Betriebspunkte
    "didok": ["service-point-v2", "service-points-actual-date", "service-points-full"],
    # HRDF 5.40
    "hrdf": ["fahrplan-{year}-hrdf-format-5-4", "timetable-54-{year}-hrdf"],
}

# Bevorzugte Ressource je Datensatz (Teilstring im Dateinamen)
PREFERRED = {
    "didok": ["actual-date-swiss-service-point", "full-swiss-service-point"],
    "hrdf": ["oev_sammlung_ch_hrdf"],
}

# Betriebspunkte aus dem eigenen Repo topo-daten (GitHub-Release, monatlich neu)
TOPO_URL = "https://github.com/VXstone/topo-daten/releases/download/vorbereitung/betriebspunkte.json"

# vorbereitete Fahrplandaten aus diesem Repo (Workflow .github/workflows/fahrplandaten.yml)
RELEASE = "https://github.com/VXstone/NGE-fahrplan/releases/download/fahrplandaten/"
RELEASE_FILES = ["stations.csv", "trips_bahn.json.gz", "stand.json"]
# optionale Zusatzdateien im Release (fehlen sie, ist das kein Fehler)
RELEASE_OPTIONAL = ["zugzahlen.csv.gz", "zugzahlen_monat.csv.gz"]

# Zugzahlen von data.sbb.ch (Personen- und Gueterzuege je Streckenabschnitt).
# data.sbb.ch sperrt manche Umgebungen (Chat-Sandbox) – aus GitHub Actions erreichbar.
SBB_EXPORT = "https://data.sbb.ch/api/explore/v2.1/catalog/datasets/{}/exports/csv?delimiter=%3B"
ZUGZAHLEN = {
    "zugzahlen.csv.gz": "zugzahlen",                # Jahreswerte je Abschnitt
    "zugzahlen_monat.csv.gz": "zugzahlen_pro_monat",  # DTV je Monat, Gueterzuege separat (DTV_G_*)
}

UA = {"User-Agent": "nge-fahrplan/0.1 (+https://github.com/OpenRailAssociation/netzgrafik-editor-frontend)"}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def find_resource(kind: str, year: int | None = None) -> dict:
    """Neueste passende Ressource (dict mit url, name, issued) eines Datensatzes.
    Probiert mehrere CKAN-Instanzen und Slugs durch."""
    tried = []
    for slug in DATASETS[kind]:
        slug = slug.format(year=year or "")
        for api in CKAN:
            try:
                pkg = _get_json(api.format(slug))
            except Exception as e:
                tried.append(f"{api.format(slug)}: {type(e).__name__}")
                continue
            if not pkg.get("success"):
                tried.append(f"{api.format(slug)}: success=false")
                continue
            res = pkg["result"]["resources"]
            for pref in PREFERRED[kind]:
                cand = []
                for r in res:
                    u = r.get("download_url") or r.get("url") or ""
                    if pref in u.lower() and u.lower().split("?")[0].endswith((".csv", ".zip")):
                        cand.append((r.get("issued") or r.get("created") or "", u))
                if cand:
                    cand.sort(reverse=True)
                    issued, u = cand[0]
                    return {"url": u, "name": u.split("?")[0].rsplit("/", 1)[-1], "issued": issued}
            tried.append(f"{api.format(slug)}: {len(res)} Ressourcen, keine passt zu {PREFERRED[kind]}")
    raise RuntimeError("Keine Ressource gefunden:\n  " + "\n  ".join(tried))


def download(url: str, dest: Path, force: bool = False) -> Path:
    """Streamt eine Datei auf die Platte (mit Fortschritt), ueberspringt vorhandene."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  vorhanden: {dest}", file=sys.stderr)
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total and sys.stderr.isatty():
                print(f"\r  {dest.name}: {done/1e6:7.1f} / {total/1e6:.1f} MB", end="", file=sys.stderr)
    if sys.stderr.isatty():
        print(file=sys.stderr)
    os.replace(tmp, dest)
    return dest


def fetch(kind: str, data_dir: Path, year: int | None = None, url: str | None = None,
          force: bool = False) -> Path:
    if kind == "release":
        for f in RELEASE_FILES:
            download((url or RELEASE) + f, data_dir / f, force=True)
        for f in RELEASE_OPTIONAL:
            try:
                download((url or RELEASE) + f, data_dir / f, force=True)
            except Exception as e:
                print(f"  {f}: nicht im Release ({type(e).__name__})", file=sys.stderr)
        return data_dir / "trips_bahn.json.gz"
    if kind == "zugzahlen":
        return fetch_zugzahlen(data_dir)
    if kind == "topo":
        return download(url or TOPO_URL, data_dir / "betriebspunkte.json", force=True)
    if url is None:
        info = find_resource(kind, year)
        url, name = info["url"], info["name"]
        print(f"{kind}: {name} (publiziert {info['issued']})", file=sys.stderr)
    else:
        name = url.rsplit("/", 1)[-1].split("?")[0] or f"{kind}.dat"
    path = download(url, data_dir / name, force=force)
    # stabiler Alias, damit die anderen Befehle ohne Dateinamen auskommen
    alias = data_dir / ({"didok": "didok", "hrdf": "hrdf"}[kind] + Path(name).suffix)
    if alias != path:
        try:
            if alias.exists() or alias.is_symlink():
                alias.unlink()
            alias.symlink_to(path.name)
        except OSError:
            shutil.copyfile(path, alias)
    return path


def fetch_zugzahlen(data_dir: Path) -> Path:
    """Laedt die beiden Zugzahlen-Datensaetze von data.sbb.ch als gzip-CSV (';').

    zugzahlen.csv.gz       Jahreswerte je Streckenabschnitt (Personen + Gueter)
    zugzahlen_monat.csv.gz DTV je Abschnitt und Monat, Gueterzuege separat (DTV_G_*)
    """
    import gzip

    data_dir.mkdir(parents=True, exist_ok=True)
    for name, slug in ZUGZAHLEN.items():
        dest = data_dir / name
        tmp = dest.with_suffix(".part")
        req = urllib.request.Request(SBB_EXPORT.format(slug), headers=UA)
        with urllib.request.urlopen(req, timeout=300) as r, gzip.open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        with gzip.open(tmp, "rt", encoding="utf-8") as f:
            zeilen = sum(1 for _ in f) - 1
        if zeilen < 10:
            raise RuntimeError(f"{slug}: nur {zeilen} Zeilen – Export unvollstaendig?")
        os.replace(tmp, dest)
        print(f"  {name}: {zeilen} Zeilen", file=sys.stderr)
    return data_dir / "zugzahlen_monat.csv.gz"
