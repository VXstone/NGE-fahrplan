# Übergabe NGE-fahrplan + fahrplan-verstehen – Stand 23.11.2026

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
- Jede Änderung am Leser mit der **Gegenprobe Reisezüge vs. HRDF** prüfen (`tools/qa.py`, Abschnitt 2): Trefferquote
  darf nicht sinken (Stand 98,6 % auf ±1,5′, alle 161 Felder 2026).
- Topologie/Gleiszahlen gehören nach **VXstone/topo-daten** (eigene Übergabe dort), hier nichts Paralleles bauen.
- **Am Ende jedes Schritts** in der Antwort an Daniel: direkte Links zu allem, was er ausführen muss (PR, Workflow-Seite
  mit «Run workflow», Eingabe z. B. `year=2025`), in der Reihenfolge, und den **Prompt für den nächsten Schritt** zum Kopieren.

### Links zum Ausführen
| Was | Link |
|---|---|
| PRs mergen | https://github.com/VXstone/NGE-fahrplan/pulls · https://github.com/VXstone/fahrplan-verstehen/pulls |
| grafapla (Run workflow, `year` 2026 bzw. 2025) | https://github.com/VXstone/NGE-fahrplan/actions/workflows/grafapla.yml |
| Fahrplandaten (HRDF, Zugzahlen) | https://github.com/VXstone/NGE-fahrplan/actions/workflows/fahrplandaten.yml |
| Erkundung Verzeichnis/PDFs | https://github.com/VXstone/NGE-fahrplan/actions/workflows/grafapla-verzeichnis.yml |
| daten (fahrplan-verstehen: Seite, Tabelle) | https://github.com/VXstone/fahrplan-verstehen/actions/workflows/daten.yml |
| Releases | https://github.com/VXstone/NGE-fahrplan/releases · https://github.com/VXstone/fahrplan-verstehen/releases/tag/daten |
| Güterzug-Tabelle | https://claude.ai/artifact/HDh3QJrCLZqzQP5QNYoGXu |

## 1. Was wo ist

### NGE-fahrplan
| Teil | Zweck |
|---|---|
| `nge_fahrplan/` | HRDF + atlas/DIDOK + topo-daten-Betriebspunkte → NGE-JSON (Netzgrafik-Editor). Details README |
| `tools/fahrplandaten.py`, `fahrplandaten.yml` | samstags: HRDF, Stationen, **Zugzahlen** (data.sbb.ch `zugzahlen`, `zugzahlen_pro_monat`) → Release, `stand.json` |
| `tools/grafapla.py` | grafische Fahrpläne holen: `oev-info.ch`/`tp-info.ch …/grafapla/{Jahr}/G{feld}.pdf`, Listenseite mit Jahresfilter `?year=<id>&items_per_page=1000` (massgebend), `?page=N` + Proben G100–999 und Bahnkürzel × Suffix |
| `tools/grafapla_verzeichnis.py`, `grafapla-verzeichnis.yml` | Erkundung (Dispatch): Listenseiten, Filter (Jahr, EVU), einzelne PDFs (Seiten, Farben, Text) → `erkundung_verzeichnis.json` im Release grafapla-2026 |
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
D Klasse, E Achse, F–H Von/Ab/Nach, I–O Mo–So, P–X Rest), Legende. Erzeugt mit `fahrplan-verstehen/tools/gz_list.py`;
`daten.yml` legt `gueterzuege.json/.csv/.xlsx` ins Release `daten` (xlsx = Blatt «Güterzüge»).
Neue Zeilen: `gueterzuege.xlsx` aus dem Release → als Asset hochladen → `importFile` als Blatt «neu» → `insertRows` vor der letzten Zeile
(damit die COUNTIFS-Bereiche mitwachsen) → `copyCells` in Stücken à 200 Zeilen → «neu» löschen.

## 2. Datenkette und Prüfung
HRDF (opentransportdata) ─┬→ fahrplan.json.gz ─────────────┐
grafische Fahrpläne (SKI) ─→ grafapla_<J>_zuege.json.gz ─→ build_pub (Plausibilität gegen HRDF) → publikation.json.gz → Seite, Tabelle
Zugzahlen (data.sbb.ch) → Mengenabgleich (NNP-Vergleich, `abgleich_nnp_zugzahlen_2026`)

- `build_pub`: Reisezug-Nummern nur, wenn Stationen ≥ 80 % innerhalb 1,5 km vom HRDF-Laufweg und Zeiten ≥ 60 % ±3′;
  Stücke je Nummer nach Zusammenhang gruppiert, Lücken ≤ 60′ verbunden, VP mit «|» vereinigt.
- **Gegenprobe:** `python tools/qa.py grafapla_2026_zuege.json.gz fahrplan.json.gz [--felder …]` (fahrplan.json.gz aus
  Release `daten` von fahrplan-verstehen). Reisezüge gegen HRDF gleicher Nummer, je Betriebspunkt Ankunft *oder*
  Abfahrt ±1,5′; je Feld Anteil ohne Nummer und `ok` (≥ 95 %)/`abweichend`. Güterzüge sind nicht prüfbar.
- Lokaler Volllauf aller 161 PDFs: ~15 min mit `xargs -P 8` je Feld, im Hintergrund oder im Workflow.

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
- **Doppelte Stationen** wo Felder überlappen: in `build_pub.merge` bereinigt (F). Doppelungen *innerhalb* eines Felds
  bleiben (gleiche Nummer, andere VP/Lage, nächster Punkt).
- **Zeichnung** (seit D genutzt): jeder Strich ist 2× gezeichnet, Züge gleicher Trasse vervielfachen ihn (Nummern dann
  übereinander); Züge sind im Strom der Reihe nach gezeichnet (Strich, Punkt, Strich), teils gegen die Zeit, und
  springen über nicht gezeichnete Stücke (Rangierbahnhof Dänken DKW→DK). Standzeit im Rangierbahnhof = senkrechter
  Strich (LTF Lausanne-Triage), Nummer oft nur am kurzen Ausfahrstummel, in dessen Verlängerung.
- **Gleiche Nummer, andere VP und Lage** (z. B. 6147 VP 669/759, 6′ versetzt) werden beim Zusammenführen zu einem Zug
  vermengt (~0,4 % der Züge, Halte doppelt) – offen.
- **Lizenz:** Quelle «Systemaufgabe Kundeninformation (SKI), oev-info.ch, erstellt von SBB Infrastruktur bzw. den Bahnen»,
  **Lizenz ungeklärt**, überall so vermerkt. Zugzahlen: «Open use. Must provide the source» (SBB).
- Die Original-PDF-ZIPs liegen noch in den öffentlichen Releases grafapla-2026/-2025; löschen kann nur Daniel.

## 4. Offene Schritte
**Reihenfolge:** B → D → E → F → C → G. Ein Chat je Schritt, nacheinander (gleicher Code).
Einstieg (Daniel kopiert): «Weiter mit UEBERGABE.md in VXstone/NGE-fahrplan – Schritt X» = Freigabe für Branch + PR,
Workflows anstossen, Güterzug-Tabelle schreiben. Am Ende: Schritt abhaken, Nachtrag in 5, PR für die Übergabe.
Begründung: B zuerst (klein, macht die Tabelle reproduzierbar, Grundlage für alles Weitere); D bringt beim Güterverkehr
am meisten (RB Lausanne-Triage, Genève, Gotthard 531); E ist nur Nachsehen; F Schönheitsfehler; C grösserer Aufwand
mit wenig Güterverkehr; G gehört nach topo-daten und braucht die saubere Liste aus B/D/F.

**Nächster Einstieg (kopieren):** «Weiter mit UEBERGABE.md in VXstone/NGE-fahrplan – Schritt C»
Nach dem Merge eines Leser-Schritts (C, D) ausführen: grafapla `year=2026`, dann `year=2025` → daten → Claude schreibt
die Güterzug-Tabelle neu (Links oben).

- [x] **A** PR #6 mergen → `grafapla.yml` für 2026 und 2025 starten → `daten.yml` starten → Güterzug-Tabelle neu.
- [x] **B** `gz_list.py` (Güterzug-Liste mit Mustern Mo–So, Verkettung, Achse) ins Repo fahrplan-verstehen `tools/`.
- [ ] **C** Leser CJ (2026 publiziert, eigenes Layout, liefert heute nichts), BOB, MOB (nur 2025 → «Stand Fahrplan 2025»);
      seit E auch **MGB** `GMGBS`/`GMGBW` (Sommer/Winter, nur bis 2025, 1 Blatt, Zermatt–Brig + Brig–Göschenen/Disentis,
      Farben 0000ff/000000/ff0000/008000/ff8000/808000, VP «Güter» im Winterblatt) und **DB Basel Bad** `GDB1–3`
      (bis 2025, 45 S., DB-InfraGO-Layout, Farben f5ae0c/0080ff, Basel Bad Rbf → Güterverkehr). Beide überspringt der Leser.
      Danach: «Weiter mit UEBERGABE.md in VXstone/NGE-fahrplan – Schritt G»
- [x] **D** Schwache SBB-Felder: Lausanne-Triage 114–117, Genève 111–113, 151/152, 412, 451, 461, 531, 331.
      Je Feld Anteil Linien ohne Nummer messen (Gegenprobe Abschnitt 2), Ursache am PDF ansehen, nicht raten.
- [x] **E** MGB, zb: im Jahresverzeichnis `grafapla/<J>/GZVJ.pdf` bzw. `.xlsx` nachsehen (über Actions holen).
- [x] **F** Doppelte Stationen bei überlappenden Feldern entfernen (fahrplan-verstehen `build_pub.merge`, PR #10).
      Danach: «Weiter mit UEBERGABE.md in VXstone/NGE-fahrplan – Schritt C»
- [ ] **G** Gleiszahl-Abgleich: befahrene Abschnitte der Güterzüge als Eingabe an topo-daten (Schritt dort).
      Danach: Übergabe in VXstone/topo-daten weiterführen.

## 5. Nachträge
- 21.11. Violett als G (PR #5), RhB- und 636xx-Güterzüge in der Tabelle, Vereina als Autoverlad, «mod» aufgenommen;
  Tabelle 2104 Fahrten (Mo 1156, Di–Fr 1405–1442, Sa 645, So 386). Label-Korrektur Bergstrecken als PR #6 offen.
- 22.11. PR #6 drin, grafapla 2026/2025 neu, Tabelle 2156 Fahrten (Mo 1178, Di–Fr 1445–1474, Sa 667, So 402);
  Kandersteg–Brig 18, SOB 791 25 Güterzug-Fahrten, Lötschberg-Achse 58.
- 22.11. B: `gz_list.py` aus dem Chat nachgebaut (fahrplan-verstehen PR #9), Ausgabe = Tabelle (2156 Zeilen, Tage,
  Klassen, Achsen gleich). Regel ergänzt: RhB-G 5xxx über Pischahorn nicht als Vereina-Autoverlad.
- 22.11. D (PR «grafapla-felder-d»): Ursachen am PDF – gestapelte Nummern gleicher Trasse (nur 1 Zug erkannt), Nummer
  in Verlängerung von Ausfahrstummeln (Lausanne-Triage), zufällige Wahl an Verzweigungen, Sprung über Rangierbahnhof
  (Dänken). Leser nutzt jetzt Strich-Vielfachheit + Zeichenreihenfolge (Abschnitt 3). Alle 161 Felder: Gegenprobe
  98,3 → 98,6 %, G-Stücke mit Nummer 15 624 → 16 699, ohne 5 075 → 4 424, R ohne 38 673 → 31 218. G ohne: 115 61→35 %,
  152 48→38 %, 451 33→21 %, 412 +124 Züge. Rest in 113–117 = Kurzstücke im Bahnhof, 531 = Striche ausserhalb des
  Zeitfensters (stehen auf Nachbarseite). Lausanne-Triage 114–117 R bleibt ~95 % («abweichend»). `tools/qa.py` neu.
  Nach Merge: grafapla 2026+2025 und `daten.yml` gelaufen, Tabelle neu: 2179 Fahrten (Mo 1187, Di–Fr 1453–1482,
  Sa 671, So 407), Gotthard 247, Lötschberg 61; Muster-Liste A14:C38 von Hand neu (feste Werte!), Legende 98,6 %.
- 22.11. Leere Abschnitte 2026 (Blätter ab 01.06. während Totalsperren): Payerne–Murten (252), Iselle–Domodossola
  (222/223). 2025 war Payerne–Murten gezeichnet → Idee: Rückgriff auf 2025 für gesperrte Abschnitte (wie MOB in C).
- 23.11. E: **GZVJ gibt es nur 2020–2023** (BAV-Archivliste alter fahrplanfelder.ch-Links seit 2009), 2024–2027 404.
  Massgebend ist die Listenseite oev-info.ch mit Filtern Jahr (IDs 2026=2184746, 2025=1753514) und EVU. **MGB** =
  `GMGBS`/`GMGBW` 2019–2025, **2026 nicht publiziert**; fehlte bisher (Suffix S/W nicht geprobt), ebenso `GDB1–3`
  2025. **zb**: nicht unter den EVU-Filtern, keine Datei 2018–2026 → keine grafischen Fahrpläne (GZVJ nur S. 1 gelesen).
  2026 Liste = unsere 161 Dateien (vollständig). `grafapla.py` nutzt jetzt die Jahresliste; Leser überspringt GMGB*/GDB*.
  Güterzug-Tabelle unverändert (keine neuen Züge). Nach Merge: `grafapla.yml` für 2025 starten (nur Dateiliste neu).
- 23.11. F (fahrplan-verstehen PR #10): Überlappung wird in `build_pub` aufgelöst, nicht im Leser. Je Punkt: gleiche
  Zeit → eins; Stückende-Ankunft + Stückanfang-Abfahrt → ein Halt; Widerspruch → Mehrheit der Felder, dann Stück weiter
  innen (40002: 531 statt 540 bei RYUE–FL). Läufe mit Doppelpunkt R/G/L 800/129/41 → 141/54/25, Rest nur innerhalb eines
  Felds. Publikation vs. HRDF An-oder-Ab 98,99 → 99,05 %, An-und-Ab 77,5 → 78,4 %. Güterzug-Liste 2179 Zeilen, nur «via»
  bei 13 Zügen sauberer. Leser unverändert → grafapla nicht neu; nach Merge `daten.yml` starten, Tabelle (nur «via») in C mit neu.
