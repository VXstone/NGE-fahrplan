# Übergabe NGE-fahrplan + fahrplan-verstehen – Stand 22.11.2026

Kurz halten. Gelesen wird Abschnitt 0, 1 und der eigene Schritt in Abschnitt 4. Nachträge am Ende eines Schritts
**höchstens 10 Zeilen** in Abschnitt 5; wird er länger als ~60 Zeilen, die ältesten in `UEBERGABE_ARCHIV.md` verschieben.
Gilt für beide Repos: **VXstone/NGE-fahrplan** (dieses) und **VXstone/fahrplan-verstehen** (dort nur Verweis hierher).

## 0. Arbeitsweise
- **Daniel merged** PRs und legt Releases an. Aus der Sitzung: Branch pushen, PR per `gh api …/pulls` (REST);
  `gh pr create`, `gh release download/upload` gehen über GraphQL und sind gesperrt → `gh api` bzw. `curl` mit Token.
- **Netz aus der Sitzung gesperrt:** tp-info.ch, oev-info.ch, data.sbb.ch, opentransportdata.swiss. Alles Holen läuft
  über **GitHub Actions**; Ergebnisse liegen in Releases. GitHub selbst ist erreichbar.
- **Workflows anstossen:** `gh api repos/VXstone/<repo>/actions/workflows/<datei>/dispatches -X POST -f ref=main`.
  `grafapla.yml` läuft **nicht** auf Push nach main (nur Branches grafapla*), nach jedem Merge von Hand starten.
  Ein Dispatch-Lauf kann kein *neues* Release anlegen, nur in bestehende hochladen.
- **Zuerst ansehen, dann behaupten.** Was nur angenommen ist, so benennen. Vor «fehlt» in den Feldlisten nachschauen
  (BLS/SOB stecken in SBB-Feldern, siehe 3).
- Jede Änderung am Leser mit der **Gegenprobe Reisezüge vs. HRDF** prüfen (`qa.py`, Abschnitt 2): Trefferquote darf
  nicht sinken (Stand 98,4 % auf ±1,5′).
- Topologie/Gleiszahlen gehören nach **VXstone/topo-daten** (eigene Übergabe dort), hier nichts Paralleles bauen.

## 1. Was wo ist

### NGE-fahrplan
| Teil | Zweck |
|---|---|
| `nge_fahrplan/` | HRDF + atlas/DIDOK + topo-daten-Betriebspunkte → NGE-JSON (Netzgrafik-Editor). Details README |
| `tools/fahrplandaten.py`, `fahrplandaten.yml` | samstags: HRDF, Stationen, **Zugzahlen** (data.sbb.ch `zugzahlen`, `zugzahlen_pro_monat`) → Release, `stand.json` |
| `tools/grafapla.py` | grafische Fahrpläne holen: `oev-info.ch`/`tp-info.ch …/grafapla/{Jahr}/G{feld}.pdf`, Listenseiten `?page=N` + Proben G100–999 und Bahnkürzel × Suffix |
| `tools/grafapla_parse.py` | SBB-Layout lesen (Zeit senkrecht, Stationen waagrecht); auch SZU, BLS-/SOB-Felder |
| `tools/grafapla_rhb.py` | RhB-Layout (Zeit waagrecht) |
| `tools/grafapla_vp.py` | Verkehrsperioden entschlüsseln |
| `grafapla.yml` | Matrix 2026/2025 → Release `grafapla-<Jahr>`: `grafapla_<J>.json` (Dateiliste), `grafapla_<J>_zuege.json.gz` |

### fahrplan-verstehen (GitHub Pages: https://vxstone.github.io/fahrplan-verstehen/)
| Teil | Zweck |
|---|---|
| `tools/build_data.py` | HRDF-Bahnfahrten des Jahres → `web/data/fahrplan.json.gz` (Format im README) |
| `tools/build_pub.py` | grafapla-Züge → `web/data/publikation.json.gz` `{meta, st_add, tr:[[zug,kat,felder,vp,flat]]}` |
| `daten.yml` | Mi+Sa 04:41 UTC, Dispatch, Push main: beide Dateien bauen → Release `daten` + Pages |
| `web/app.js` | Seite: Strecke A–B (via) + Datum → Bildfahrplan, Knotenlupe, Kursbuch, Kreuzungen, Anschlüsse |

Seite, Funktionen:
- **Quelle** Tag / Publikation / Vergleich (`setQuelle`): Publikation = Wochentag des Datums aus den grafischen
  Fahrplänen (mit G und L); Vergleich legt HRDF darüber (wie publiziert / abweichend > 3′ / nur publiziert / nur heute).
- **Zuglauf** `?zug=<nr>&zugquelle=…` (`showZug`): ganzer Lauf eines Zugs auf der Karte; Absprung aus Panel und
  aus der Güterzug-Tabelle (Spalte «Zuglauf»).
- **Umweg-Prüfung** (`segKm`): Stück zwischen zwei Streckenstationen wird geteilt, wenn ein Zwischenpunkt > 3 km
  vom Korridor liegt (RE1 via Goppenstein, PR #7).
- **Geschätzt:** km als Luftlinie, Ein-/Zweigleisigkeit aus Begegnungen, Durchfahrtszeiten linear, Wenden ↺ vermutet.

### Güterzug-Tabelle (Claude Sheet)
«Güterzüge Schweiz – publizierter Fahrplan 2026 (Mo–So)», https://claude.ai/artifact/HDh3QJrCLZqzQP5QNYoGXu
Blätter Übersicht (COUNTIFS je Klasse/Achse × Wochentag), Güterzüge (Spalten A Zug, B Zuglauf-Link, C Verkehrstage,
D Klasse, E Achse, F–H Von/Ab/Nach, I–O Mo–So, P–X Rest), Legende. Erzeugt mit `gz_list.py` (noch nicht im Repo, s. 4).
Neue Zeilen: xlsx bauen → als Asset hochladen → `importFile` als Blatt «neu» → `insertRows` vor der letzten Zeile
(damit die COUNTIFS-Bereiche mitwachsen) → `copyCells` in Stücken à 200 Zeilen → «neu» löschen.

## 2. Datenkette und Prüfung
HRDF (opentransportdata) ─┬→ fahrplan.json.gz ─────────────┐
grafische Fahrpläne (SKI) ─→ grafapla_<J>_zuege.json.gz ─→ build_pub (Plausibilität gegen HRDF) → publikation.json.gz → Seite, Tabelle
Zugzahlen (data.sbb.ch) → Mengenabgleich (NNP-Vergleich, `abgleich_nnp_zugzahlen_2026`)

- `build_pub`: Reisezug-Nummern nur, wenn Stationen ≥ 80 % innerhalb 1,5 km vom HRDF-Laufweg und Zeiten ≥ 60 % ±3′;
  Stücke je Nummer nach Zusammenhang gruppiert, Lücken ≤ 60′ verbunden, VP mit «|» vereinigt.
- **Gegenprobe:** Reisezüge aus denselben PDFs gegen HRDF, je Feld `ok`/`abweichend`. Güterzüge sind nicht prüfbar.
- Lokaler Volllauf aller 133 SBB-PDFs dauert > 10 min: im Hintergrund oder im Workflow.

## 3. Fallstricke
- **Farben** (Linien leicht anders als Text, Toleranz 0.01): Blau 3b65a3 = G 4xxxx–6xxxx; Rot af3734 = Reisezug;
  Grün 2b7b73 = Lok/Leer; **Violett 7a4db2 = 636xx, als G geführt** (Thun–LBT–Brig, Fribourg–Bern; vermutlich Transit,
  evtl. Lichtraum). Grau 8b8b8b = Betriebspunkte ohne Halt. RhB: Blau (0,0,1) = G 5xxx, Schwarz = R, Grau = L.
- **Beschriftung** «Nummer VP», gedreht; Zuordnung über Winkel und Abstand zur Grundlinie. Auf kurzen steilen Segmenten
  (352 Bergstrecke, 791 SOB) steht die Nummer in der Verlängerung → zweiter Durchgang (PR #6).
- **«mod»** hinter der Nummer = Variante für einen Teil des Jahres → Nummer ohne «mod», als zeitweise.
- **VP:** 2-stellig xy = Tage x..y; 3-stellig x0y/xyz/xy9 = Werktage (xy8 unklar); «+» Folgetag, «*» zeitweise;
  eidg. Feiertage wie Sonntag. Zeichenerklärung: alptransit-portal, Zeichenerklaerung-graphische-Fahrplaene-dt.pdf.
- **Vereina-Autoverlad** (Pischahorn–Piz Fless) ist blau gezeichnet → Achse «Autoverlad Vereina», nicht Güterzug.
- **BLS/SOB sind enthalten**, als SBB-Felder: 351 Thun–Kandersteg, 352 Kandersteg–Brig, 361, 362, 391 Spiez–Visp–Brig,
  791 SOB. Lötschberg-Autoverlad ist in 352 nicht gezeichnet.
- **Simplon 222/223** enthalten keine Güterzüge (laut Zugzahlen ~32/Tag).
- **Achse** nach Feldnummer: 540/541/531 Gotthard, 351/352/391 Lötschberg, 222/223 Simplon (nicht nach Stationsnamen).
- Seiten sind teils doppelt gedruckt (gleiche Zeitspanne) → übersprungen. Stationskopf zweizeilig.
- **Doppelte Stationen** wo Felder überlappen (z. B. 40002 um Rynächt/Flüelen) – noch offen.
- **Lizenz:** Quelle «Systemaufgabe Kundeninformation (SKI), oev-info.ch, erstellt von SBB Infrastruktur bzw. den Bahnen»,
  **Lizenz ungeklärt**, überall so vermerkt. Zugzahlen: «Open use. Must provide the source» (SBB).
- Die Original-PDF-ZIPs liegen noch in den öffentlichen Releases grafapla-2026/-2025; löschen kann nur Daniel.

## 4. Offene Schritte
- [ ] **A** PR #6 mergen → `grafapla.yml` für 2026 und 2025 starten → `daten.yml` starten → Güterzug-Tabelle neu.
- [ ] **B** `gz_list.py` (Güterzug-Liste mit Mustern Mo–So, Verkettung, Achse) ins Repo fahrplan-verstehen `tools/`.
- [ ] **C** Leser CJ (2026 publiziert, eigenes Layout, liefert heute nichts), BOB, MOB (nur 2025 → «Stand Fahrplan 2025»).
- [ ] **D** Schwache SBB-Felder: Lausanne-Triage 114–117, Genève 111–113, 151/152, 412, 451, 461, 531, 331.
- [ ] **E** MGB, zb: im Jahresverzeichnis `grafapla/<J>/GZVJ.pdf` bzw. `.xlsx` nachsehen (über Actions holen).
- [ ] **F** Doppelte Stationen bei überlappenden Feldern entfernen.
- [ ] **G** Gleiszahl-Abgleich: befahrene Abschnitte der Güterzüge als Eingabe an topo-daten (Schritt dort).

## 5. Nachträge
- 21.11. Violett als G (PR #5), RhB- und 636xx-Güterzüge in der Tabelle, Vereina als Autoverlad, «mod» aufgenommen;
  Tabelle 2104 Fahrten (Mo 1156, Di–Fr 1405–1442, Sa 645, So 386). Label-Korrektur Bergstrecken als PR #6 offen.
