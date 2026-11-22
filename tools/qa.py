"""Gegenprobe grafische Fahrpläne: Reisezüge aus den PDFs gegen die HRDF.

  python tools/qa.py <grafapla_J_zuege.json.gz> <fahrplan.json.gz> [--felder 111,112] [--tol 1.5] [--json out.json]

fahrplan.json.gz = Jahresdaten aus VXstone/fahrplan-verstehen (Release «daten»).
Je Reisezug (Kategorie R) mit derselben Nummer in der HRDF werden die gemeinsamen Betriebspunkte
verglichen: ein Punkt trifft, wenn Ankunft oder Abfahrt ± tol Minuten stimmt (wie build_pub in
fahrplan-verstehen; über Mitternacht gerechnet). Gezählt wird gegen die
am besten passende HRDF-Fahrt der Nummer. Trefferquote = passende / verglichene Betriebspunkte.
Je Feld: Anteil Linienzüge ohne Nummer (G, R, L) und Trefferquote R; Feld «ok» ab 95 %.
Güterzüge haben keine HRDF-Fahrt und sind so nicht prüfbar.
"""
import argparse
import gzip
import json
from collections import defaultdict


def cd(x, y):
    d = abs(x - y) % 1440
    return min(d, 1440 - d)


def lade_hrdf(fn):
    fp = json.load(gzip.open(fn, "rt", encoding="utf-8"))
    H = defaultdict(list)
    for fnr, adm, cat, line, bf, flat in fp["tr"]:
        n = fnr.split("+")[0].lstrip("0")
        h = {}
        for k in range(0, len(flat), 4):
            ab = fp["st"][flat[k]][4]
            an_, ab_ = flat[k + 1], flat[k + 2]
            if ab and (an_ is not None or ab_ is not None):
                h[ab] = ((an_ if an_ is not None else ab_) % 1440, (ab_ if ab_ is not None else an_) % 1440)
        if h:
            H[n].append(h)
    return H


def pruefe(zuege, H, felder=None, tol=1.5):
    res = {}
    for f in zuege["felder"]:
        if felder and f["feld"] not in felder:
            continue
        r = dict(ohne={}, mit={}, n=0, ok=0, zuege_geprueft=0)
        for kat, blk in f.get("kat", {}).items():
            r["mit"][kat] = len(blk["zuege"])
            r["ohne"][kat] = blk.get("ohne_nummer", 0)
        for z in f.get("kat", {}).get("R", {}).get("zuege", []):
            hs = H.get(z["zug"].lstrip("0").rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            if not hs:
                continue
            best = None
            for h in hs:
                n = ok = 0
                for s, an, ab in z["halte"]:
                    if s in h:
                        n += 1
                        ok += min(cd(an, h[s][0]), cd(ab, h[s][1])) <= tol
                if n and (best is None or ok / n > best[1] / best[0] or (ok / n == best[1] / best[0] and n > best[0])):
                    best = (n, ok)
            if best:
                r["zuege_geprueft"] += 1
                r["n"] += best[0]
                r["ok"] += best[1]
        r["quote"] = r["ok"] / r["n"] if r["n"] else None
        res[f["feld"]] = r
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("zuege")
    ap.add_argument("fahrplan")
    ap.add_argument("--felder")
    ap.add_argument("--tol", type=float, default=1.5)
    ap.add_argument("--json")
    a = ap.parse_args()
    z = json.load(gzip.open(a.zuege, "rt", encoding="utf-8") if a.zuege.endswith(".gz") else open(a.zuege, encoding="utf-8"))
    res = pruefe(z, lade_hrdf(a.fahrplan), set(a.felder.split(",")) if a.felder else None, a.tol)
    print(f"{'Feld':6} {'G mit/ohne':>11} {'Anteil':>6} {'R mit/ohne':>11} {'Anteil':>6} {'R geprüft':>9} {'Quote':>6}")
    N = OK = 0
    for feld, r in sorted(res.items()):
        def anteil(k):
            m, o = r["mit"].get(k, 0), r["ohne"].get(k, 0)
            return f"{m:>5}/{o:<5}", f"{o / (m + o):6.0%}" if m + o else "     -"
        g, ga = anteil("G")
        rr, ra = anteil("R")
        q = f"{r['quote']:6.1%}" if r["quote"] is not None else "     -"
        print(f"{feld:6} {g} {ga} {rr} {ra} {r['zuege_geprueft']:>9} {q} {'' if r['quote'] is None else ('ok' if r['quote'] >= 0.95 else 'abweichend')}")
        N += r["n"]
        OK += r["ok"]
    print(f"Gesamt: {OK}/{N} Betriebspunkte = {OK / N:.1%} auf ±{a.tol}′" if N else "keine Reisezüge geprüft")
    if a.json:
        json.dump(dict(gesamt=OK / N if N else None, felder=res), open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
