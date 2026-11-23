"""Jahresverzeichnis der grafischen Fahrpläne (GZVJ) und Nicht-SBB-Bahnen nachsehen.

  python tools/grafapla_verzeichnis.py <ausgabe.json> [--jahre 2027 2026 2025]

Nur Erkundung, kein Leser: probiert GZVJ.pdf/.xlsx unter den bekannten Pfaden,
blättert die Listenseite von oev-info.ch (de/fr) durch und sucht dort nach
MGB/zb (Matterhorn Gotthard Bahn, Zentralbahn) und weiteren Bahnkürzeln.
Ergebnis als JSON (Statuscodes, gefundene Links, Textstellen, Verzeichnistext).
"""
import argparse, html as htmlmod, io, json, re, urllib.error, urllib.request

UA = {"User-Agent": "nge-fahrplan/0.1 (+https://github.com/VXstone/NGE-fahrplan)"}
HOSTS = ["https://www.oev-info.ch", "https://www.tp-info.ch", "https://tp-info.ch"]
LISTEN = {"de": "https://www.oev-info.ch/de/fahrplan-aktuell/grafische-fahrplaene?page={p}",
          "fr": "https://www.oev-info.ch/fr/horaire-actuel/horaires-graphiques?page={p}"}
SUCH = re.compile(r"MGB|Matterhorn|Gotthard\s*Bahn|\bzb\b|Zentralbahn|Brünig|Furka|Zermatt|Engelberg|"
                  r"Verzeichnis|GZVJ|xlsx|Jahr", re.I)
KUERZEL = ["MGB", "Mgb", "mgb", "ZB", "zb", "Zb", "BOB", "MOB", "CJ", "GGB", "BLM", "WAB", "JB", "RB", "PB"]

ap = argparse.ArgumentParser(); ap.add_argument("out")
ap.add_argument("--jahre", nargs="+", type=int, default=[2027, 2026, 2025])
ap.add_argument("--pdfs", nargs="*", default=[], help="einzelne PDFs ansehen (Seiten, Text, Linienfarben)")
ap.add_argument("--nur-pdfs", action="store_true")
a = ap.parse_args()
# Jahres-IDs des Filters «year» auf der Listenseite (aus der ersten Erkundung)
JAHR_ID = {2026: 2184746, 2025: 1753514, 2024: 638390, 2023: 69400}
JAHRLISTE = "https://www.oev-info.ch/de/fahrplan-aktuell/grafische-fahrplaene?year={id}&items_per_page=1000"


def hole(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""
    except Exception as e:  # noqa
        return type(e).__name__, "", b""


def text_aus(name, data):
    if data[:4] == b"%PDF":
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        return "\n".join(p.get_text() for p in doc), [l.get("uri") for p in doc for l in p.get_links() if l.get("uri")]
    if data[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        zeilen, links = [], []
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                vals = [str(c.value) for c in row if c.value is not None]
                if vals:
                    zeilen.append(f"[{ws.title}] " + " | ".join(vals))
                for c in row:
                    if c.hyperlink and c.hyperlink.target:
                        links.append(c.hyperlink.target)
        return "\n".join(zeilen), links
    return data[:20000].decode("utf-8", "ignore"), []


def pdf_ansehen(url):
    import fitz
    from collections import Counter
    st, ct, data = hole(url)
    e = {"url": url, "status": st, "kb": len(data) // 1024}
    if st != 200 or data[:4] != b"%PDF":
        return e
    doc = fitz.open(stream=data, filetype="pdf")
    e["seiten"] = len(doc)
    e["format"] = [round(doc[0].rect.width), round(doc[0].rect.height)]
    farben, nummern = Counter(), Counter()
    for i, p in enumerate(doc):
        if i < 6:
            for d in p.get_drawings():
                c = d.get("color")
                if c:
                    farben["%02x%02x%02x" % tuple(int(round(v * 255)) for v in c[:3])] += 1
        for w in p.get_text("words"):
            if re.fullmatch(r"\d{3,5}[A-Z]?", w[4]):
                nummern[len(re.sub(r"\D", "", w[4]))] += 1
    e["farben_s1_6"] = farben.most_common(12)
    e["nummern_nach_stellen"] = dict(nummern)
    e["text_s1"] = doc[0].get_text()[:4000]
    e["text_alle"] = "\n".join(p.get_text() for p in doc)[:60000] if len(doc) <= 12 else ""
    return e


erg = {"verzeichnis": [], "listen": {}, "kuerzel": [], "pdfs": [], "jahrlisten": {}}
if a.pdfs:
    erg["pdfs"] = [pdf_ansehen(u) for u in a.pdfs]
# Jahreslisten (alle Einträge eines Jahres auf einer Seite)
for y, jid in JAHR_ID.items():
    st, ct, data = hole(JAHRLISTE.format(id=jid))
    h = data.decode("utf-8", "ignore")
    erg["jahrlisten"][y] = {"status": st, "links": sorted(set(re.findall(r"/grafapla/\d{4}/[^\"'?#]+\.(?:pdf|xlsx)", h)))}
if a.nur_pdfs:
    json.dump(erg, open(a.out, "w"), ensure_ascii=False, indent=1)
    raise SystemExit(0)
# 1) Jahresverzeichnis
for y in a.jahre:
    for host in HOSTS:
        for n in ("GZVJ.pdf", "GZVJ.xlsx", "GZVJ.xls", "gzvj.pdf", "gzvj.xlsx", f"GZVJ_{y}.pdf", f"GZVJ{y}.pdf"):
            url = f"{host}/sites/default/files/grafapla/{y}/{n}"
            st, ct, data = hole(url)
            e = {"url": url, "status": st, "typ": ct, "bytes": len(data)}
            if st == 200 and data[:4] in (b"%PDF", b"PK\x03\x04"):
                txt, links = text_aus(n, data)
                e["text"], e["links"] = txt[:200000], links
            erg["verzeichnis"].append(e)
        if any(v["status"] == 200 and "text" in v for v in erg["verzeichnis"] if f"/{y}/" in v["url"]):
            break
# 2) Listenseiten
for sp, muster in LISTEN.items():
    seiten, leer = [], 0
    for p in range(0, 60):
        st, ct, data = hole(muster.format(p=p))
        h = data.decode("utf-8", "ignore")
        links = sorted(set(re.findall(r"href=\"([^\"]*(?:grafapla|\.pdf|\.xlsx)[^\"]*)\"", h)))
        text = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S))))
        treffer = sorted({text[max(0, m.start() - 120): m.end() + 120] for m in SUCH.finditer(text)})
        selects = re.findall(r"<select[^>]*name=\"([^\"]+)\"[^>]*>(.*?)</select>", h, re.S)
        seiten.append({"seite": p, "status": st, "links": links, "treffer": treffer[:60],
                       "selects": [{"name": n, "optionen": re.findall(r"<option[^>]*value=\"([^\"]*)\"[^>]*>([^<]*)<", o)}
                                   for n, o in selects],
                       "text": text[:6000] if p == 0 else ""})
        leer = leer + 1 if not links else 0
        if st != 200 or leer >= 2:
            break
    erg["listen"][sp] = seiten
# 3) Kürzel-Proben MGB/zb und weitere
for y in a.jahre:
    for k in KUERZEL:
        for s in ["", "1", "2", "3", "4", "5", "6", "_1", "_2", "-1", "-2"]:
            url = f"{HOSTS[0]}/sites/default/files/grafapla/{y}/G{k}{s}.pdf"
            st, ct, data = hole(url, timeout=30)
            if st == 200 and data[:4] == b"%PDF":
                erg["kuerzel"].append({"url": url, "kb": len(data) // 1024})
json.dump(erg, open(a.out, "w"), ensure_ascii=False, indent=1)
ok = [v["url"] for v in erg["verzeichnis"] if "text" in v]
print("Verzeichnis gefunden:", ok)
print("Kürzel-PDFs:", [k["url"] for k in erg["kuerzel"]])
for sp, s in erg["listen"].items():
    print(sp, len(s), "Seiten,", sum(len(x["links"]) for x in s), "Links")
