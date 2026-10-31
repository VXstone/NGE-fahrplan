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

CKAN = "https://ckan.opendata.swiss/api/3/action/package_show?id={}"

# Datensatz-Slugs auf opendata.swiss
DATASETS = {
    # atlas v2 (Nachfolger DIDOK) – alle Dienststellen inkl. Betriebspunkte
    "didok": "service-point-v2",
    # HRDF 5.40 – {year} wird ersetzt
    "hrdf": "fahrplan-{year}-hrdf-format-5-4",
}

# Bevorzugte Ressource je Datensatz (Teilstring im Dateinamen)
PREFERRED = {
    "didok": ["actual-date-swiss-service-point", "full-swiss-service-point"],
    "hrdf": ["oev_sammlung_ch_hrdf"],
}

UA = {"User-Agent": "nge-fahrplan/0.1 (+https://github.com/OpenRailAssociation/netzgrafik-editor-frontend)"}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def find_resource(kind: str, year: int | None = None) -> dict:
    """Neueste passende Ressource (dict mit url, name, issued) eines Datensatzes."""
    slug = DATASETS[kind].format(year=year or "")
    pkg = _get_json(CKAN.format(slug))
    if not pkg.get("success"):
        raise RuntimeError(f"CKAN: Datensatz {slug} nicht gefunden")
    res = pkg["result"]["resources"]
    for pref in PREFERRED[kind]:
        cand = [r for r in res
                if pref in (r.get("download_url") or r.get("url") or "").lower()
                and (r.get("download_url") or r.get("url", "")).lower().endswith((".csv", ".zip"))]
        if cand:
            cand.sort(key=lambda r: (r.get("issued") or r.get("created") or "",
                                     r.get("download_url") or r.get("url")), reverse=True)
            r = cand[0]
            return {"url": r.get("download_url") or r["url"],
                    "name": (r.get("download_url") or r["url"]).rsplit("/", 1)[-1],
                    "issued": r.get("issued") or r.get("created")}
    raise RuntimeError(f"Keine passende Ressource in {slug} gefunden "
                       f"({len(res)} Ressourcen, gesucht: {PREFERRED[kind]})")


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
