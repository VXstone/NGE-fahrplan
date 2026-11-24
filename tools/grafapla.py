"""Grafische Fahrpläne (Bildfahrpläne) von tp-info.ch holen.

  python tools/grafapla.py <ausgabeordner> [--year 2026]

Die SBB publiziert pro Fahrplanfeld einen grafischen Fahrplan als PDF
(tp-info.ch/sites/default/files/grafapla/<Jahr>/G<Feld>.pdf). Darin stehen auch
Güterzüge (5-stellige Zugnummern, Suffix F = fakultativ). Es gibt kein
Verzeichnis-Listing; darum: Verzeichnis GZVJ (xlsx/pdf) auswerten und zusätzlich
alle Feldnummern 100–999 (plus 00d/00f Zeichenerklärung) durchprobieren.
Seit Schritt E: GZVJ gibt es nur 2020–2023 (BAV-Archivliste, seit 2024 404). Massgebend ist die
Listenseite mit Jahresfilter (?year=<id>&items_per_page=1000); dort stehen auch Namen, die das
Durchprobieren nicht trifft (2025: GMGBS/GMGBW Sommer/Winter, GDB1–3 DB Basel Bad).
Ergebnis: grafapla_<Jahr>.zip + grafapla_<Jahr>.json (Liste, Titel, Grösse).
"""
import argparse, io, json, re, sys, time, urllib.request, zipfile, concurrent.futures as cf
from pathlib import Path

UA = {"User-Agent": "nge-fahrplan/0.1 (+https://github.com/VXstone/NGE-fahrplan)"}
BASES = ["https://www.oev-info.ch/sites/default/files/grafapla/{y}/",
         "https://www.tp-info.ch/sites/default/files/grafapla/{y}/",
         "https://tp-info.ch/sites/default/files/grafapla/{y}/"]
# Liste aller Bahnen (SBB und übrige, z. B. Blonay–Chamby): Seitenweise, 25 Einträge je Seite
LISTE = "https://www.oev-info.ch/de/fahrplan-aktuell/grafische-fahrplaene?page={p}"

ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--year", type=int, default=2026)
a = ap.parse_args(); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); y = a.year


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def first_ok(name, jahr=None):
    for b in BASES:
        try:
            data = get(b.format(y=jahr or y) + name)
            if data[:4] == b"%PDF" or name.endswith(".xlsx"):
                return b.format(y=jahr or y) + name, data
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
# 1b) Listenseiten von oev-info.ch durchblättern (enthält auch die Nicht-SBB-Strecken)
titel = {}
leer = 0
for pg in range(0, 200):
    try:
        html = get(LISTE.format(p=pg)).decode("utf-8", "ignore")
    except Exception as e:  # noqa
        log["fehler"].append(f"Liste Seite {pg}: {type(e).__name__}")
        break
    neu = 0
    for m in re.finditer(rf"/grafapla/{y}/([^\"'/?#]+\.pdf)", html):
        n = m.group(1)
        neu += 1          # Links auf der Seite (auch schon bekannte)
        names.add(n)
    for m in re.finditer(r">\s*(G[0-9A-Za-z_-]+)\s*<.*?>\s*([^<>]{3,120}?)\s*<", html, re.S):
        titel.setdefault(m.group(1), m.group(2).strip())
    leer = leer + 1 if neu == 0 else 0
    if leer >= 3:
        break
# 1c) Liste mit Jahresfilter: Jahres-ID aus dem Auswahlfeld «year» der ersten Listenseite
try:
    html = get(LISTE.format(p=0)).decode("utf-8", "ignore")
    sel = re.search(r'<select[^>]*name="year"[^>]*>(.*?)</select>', html, re.S)
    jid = dict((t.strip(), v) for v, t in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)<', sel.group(1))).get(str(y))
    if jid:
        html = get(f"https://www.oev-info.ch/de/fahrplan-aktuell/grafische-fahrplaene?year={jid}&items_per_page=1000").decode("utf-8", "ignore")
        jl = set(re.findall(rf"/grafapla/{y}/([^\"'/?#]+\.pdf)", html))
        log["aus_jahresliste"] = len(jl)
        names |= jl
    else:
        log["fehler"].append(f"Jahresfilter: keine ID für {y}")
except Exception as e:  # noqa
    log["fehler"].append(f"Jahresliste: {type(e).__name__}")
log["aus_liste"] = len(names)
log["listenseiten"] = pg + 1
# 2) Durchprobieren
names |= {f"G{n}.pdf" for n in range(100, 1000)} | {"G00d.pdf", "G00f.pdf", "G00i.pdf"}
# Bahnen, deren Fahrpläne unter ihrem Kürzel liegen (z. B. GBOB.pdf, GRhB1.pdf)
BAHNEN = ["AB", "AOMC", "ASD", "ASM", "AVA", "BAM", "BC", "BDWM", "BLM", "BLS", "BLT", "BOB", "BRB", "CJ", "DFB", "FART",
          "FB", "FLP", "FW", "GGB", "JB", "LEB", "MBC", "MGB", "MIB", "MOB", "MVR", "NStCM", "NSTCM", "OeBB", "PB", "RB",
          "RBS", "RhB", "RHB", "SBB", "SOB", "STB", "SZU", "TB", "TMR", "TPC", "TPF", "TRAVYS", "TRN", "TRA", "WAB",
          "WB", "WSB", "zb", "ZB", "ZSG", "TL", "SGV", "VZO", "SMC", "SNB", "UeBB", "GoldenPass", "BLSN"]
names |= {f"G{b}{n}.pdf" for b in BAHNEN for n in ["", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]}


VORJAHR = ["GMGBS.pdf", "GMGBW.pdf", "GMOB.pdf", "GBOB.pdf", "GCJ.pdf"]


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
    # Vorjahr (Schritt C): Blätter mit eigenem Leser, die dieses Jahr fehlen oder nicht lesbar sind (MGB, MOB, BOB
    # nur bis 2025; CJ 2026 ohne Textebene). Liegen im ZIP unter vorjahr/, grafapla_parse nimmt sie nur als Ersatz.
    log["vorjahr"] = {}
    z.writestr("vorjahr/jahr.txt", str(y - 1))
    for name in VORJAHR:
        if name in log["dateien"] and not name.startswith("GCJ"):
            continue
        url, data = first_ok(name, y - 1)
        if data and data[:4] == b"%PDF":
            z.writestr("vorjahr/" + name, data)
            log["vorjahr"][name] = {"url": url, "kb": len(data) // 1024}
print(f"{len(log['dateien'])} PDFs, Vorjahr {len(log['vorjahr'])}", file=sys.stderr)
(out / f"grafapla_{y}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1))
sys.exit(0 if log["dateien"] else 1)
