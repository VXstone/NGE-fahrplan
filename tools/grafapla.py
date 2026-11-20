"""Grafische Fahrpläne (Bildfahrpläne) von tp-info.ch holen.

  python tools/grafapla.py <ausgabeordner> [--year 2026]

Die SBB publiziert pro Fahrplanfeld einen grafischen Fahrplan als PDF
(tp-info.ch/sites/default/files/grafapla/<Jahr>/G<Feld>.pdf). Darin stehen auch
Güterzüge (5-stellige Zugnummern, Suffix F = fakultativ). Es gibt kein
Verzeichnis-Listing; darum: Verzeichnis GZVJ (xlsx/pdf) auswerten und zusätzlich
alle Feldnummern 100–999 (plus 00d/00f Zeichenerklärung) durchprobieren.
Ergebnis: grafapla_<Jahr>.zip + grafapla_<Jahr>.json (Liste, Titel, Grösse).
"""
import argparse, io, json, re, sys, time, urllib.request, zipfile, concurrent.futures as cf
from pathlib import Path

UA = {"User-Agent": "nge-fahrplan/0.1 (+https://github.com/VXstone/NGE-fahrplan)"}
BASES = ["https://www.tp-info.ch/sites/default/files/grafapla/{y}/",
         "https://tp-info.ch/sites/default/files/grafapla/{y}/"]

ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--year", type=int, default=2026)
a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); y = a.year


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def first_ok(name):
    for b in BASES:
        try:
            data = get(b.format(y=y) + name)
            if data[:4] == b"%PDF" or name.endswith(".xlsx"):
                return b.format(y=y) + name, data
        except Exception:
            pass
    return None, None


log = {"jahr": y, "quellen": [], "dateien": {}, "fehler": []}
names = set()
# 1) Verzeichnis
for vz in ("GZVJ.xlsx", "GZVJ.pdf"):
    url, data = first_ok(vz)
    if not data:
        continue
    log["quellen"].append(url)
    txt = ""
    if vz.endswith(".xlsx"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            txt = " ".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    else:
        txt = data.decode("latin-1", "ignore")
    for m in re.finditer(rf"/{y}/(G[0-9A-Za-z_]+)\.pdf", txt):
        names.add(m.group(1) + ".pdf")
log["aus_verzeichnis"] = len(names)
# 2) Durchprobieren
names |= {f"G{n}.pdf" for n in range(100, 1000)} | {"G00d.pdf", "G00f.pdf", "G00i.pdf"}


def fetch(name):
    url, data = first_ok(name)
    return name, url, data


zbuf = out / f"grafapla_{y}.zip"
with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_STORED) as z, cf.ThreadPoolExecutor(8) as ex:
    for name, url, data in ex.map(fetch, sorted(names)):
        if not data or data[:4] != b"%PDF":
            continue
        z.writestr(name, data)
        head = data[:200000].decode("latin-1", "ignore")
        log["dateien"][name] = {"url": url, "kb": len(data) // 1024}
print(f"{len(log['dateien'])} PDFs", file=sys.stderr)
(out / f"grafapla_{y}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
sys.exit(0 if log["dateien"] else 1)
