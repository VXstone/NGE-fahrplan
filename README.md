# nge-fahrplan

DIDOK-/atlas-Dienststellen und den offiziellen Schweizer Fahrplan (HRDF) abfragen
und daraus Netzgrafik-Editor-Dateien zeichnen
([OpenRailAssociation/netzgrafik-editor-frontend](https://github.com/OpenRailAssociation/netzgrafik-editor-frontend)).

Reines Python ≥ 3.10, **keine Abhängigkeiten**. Fasst den Workflow aus dem
`NGE_JSON_Cookbook.md` (Projekt „NGE Files") in ein wiederverwendbares Werkzeug.

```
 opentransportdata.swiss                       dieses Repo                         NGE
 ┌────────────────────────┐   fetch   ┌────────────┐ stations ┌──────────────┐
 │ atlas Service Points   │ ────────► │ data/      │ ───────► │ stations.csv │──┐
 │ (Nachfolger DIDOK)     │           │  didok.csv │          └──────────────┘  │
 │ Fahrplan HRDF 5.40 ZIP │ ────────► │  hrdf.zip  │──┐                         │
 └────────────────────────┘           └────────────┘  │ extract                 │ build
                                                      ▼                         ▼
                                    trips.json ─suggest─► spec.json ──────► netzgrafik.json
                                    (Einzelfahrten)       (Taktlinien,       (Import in NGE)
                                                           von Hand prüfbar)
```

## Schnellstart

```bash
git clone <repo> && cd nge-fahrplan
python -m nge_fahrplan fetch                 # neueste atlas-CSV + HRDF-ZIP nach data/ (~500 MB)
python -m nge_fahrplan stations              # data/stations.csv (Kürzel, Name, Nummer, WGS84)

# Region per Liste (Reihenfolge = Linienrichtung) ...
python -m nge_fahrplan run --stations BN,KZ,INS,NE,CF,LL --out neuenburg.json
# ... oder per Umkreis
python -m nge_fahrplan run --around OL --radius 12 --out olten.json
```

`run` macht `extract` → `suggest` → `build` → `validate` und legt die
Zwischenstände in `work/` ab. Für Qualitätsarbeit die Schritte einzeln:

```bash
python -m nge_fahrplan find "Chaux"                          # Kürzel nachschlagen
python -m nge_fahrplan extract --stations BN,KZ,INS,NE --out trips.json
python -m nge_fahrplan lines   --trips trips.json            # QA-Tabelle: Linie, Lagen, Takt
python -m nge_fahrplan suggest --trips trips.json --out spec.json
#   spec.json von Hand bereinigen (Namen, "skip": true, Takt, Zeiten ...)
python -m nge_fahrplan build   --spec spec.json --out netzgrafik.json
python -m nge_fahrplan departures netzgrafik.json NE         # Minuten vs. SMA-Netzgrafik
```

Knoten in NGE verschoben? Positionen übernehmen und neu bauen:

```bash
python -m nge_fahrplan positions netzgrafik_aus_nge.json --out positions.json
python -m nge_fahrplan build --spec spec.json --positions positions.json
```

Optional installieren (`pip install -e .`), dann heisst der Befehl `nge-fahrplan`.

## Datenquellen

| Was | Datensatz | Befehl |
|---|---|---|
| Dienststellen (DIDOK → atlas v2): Nummer, Kürzel, Name, Koordinaten | opendata.swiss `service-point-v2` (`actual-date-swiss-service-point.csv`) | `fetch --didok` |
| Fahrplan | opendata.swiss `fahrplan-JJJJ-hrdf-format-5-4` (HRDF 5.40, 2× pro Woche neu) | `fetch --hrdf --year 2026` |
| Betriebspunkte inkl. Abzweigstellen («Olten Ost (Abzw)») | Release `vorbereitung` von [VXstone/topo-daten](https://github.com/VXstone/topo-daten) (`betriebspunkte.json`, dort monatlich aus data.sbb.ch «Linie mit Betriebspunkten» + OSM gebaut) | `fetch --topo` |
| Alternativ | `haltestelle-haltekante.csv` / alter DIDOK-Export von data.sbb.ch (manuell herunterladen, data.sbb.ch sperrt Skripte) | `stations --didok datei.csv` |

`fetch` sucht die jeweils neueste Ressource über die CKAN-API von opendata.swiss;
mit `--url` geht auch ein direkter Link. `stations` nimmt alle vorhandenen
Quellen zusammen: atlas zuerst, topo-daten ergänzt Abzweigstellen und
Betriebspunkte ohne Publikumsverkehr (topo-daten allein reicht nicht: es deckt
nur SBB-Linien ab, z.B. fehlt Gampelen an der BLS-Strecke). Stationen ohne Eintrag in der
DIDOK-Datei (v.a. Ausland) werden aus HRDF `BAHNHOF`/`BFKOORD_WGS` ergänzt.

## Was automatisch passiert (Cookbook-Regeln)

- **Metadaten** (Kategorien, Takte, Zeitkategorien, Farben) 1:1 aus
  `netzgrafik_default.json` des NGE-Repos – nie selbst erfunden. Mit
  `build --metadata eigener_export.json` andere Quelle nehmen.
- **PortAlignment** Top=0/Bottom=1/Left=2/Right=3 aus der Geometrie,
  `positionIndex` nach Lage des Nachbarknotens sortiert.
- **Transitions** an jedem Zwischenhalt; Durchfahrten (HRDF: negative Zeit)
  als `isNonStopTransit`.
- **Echte Rückfahrzeiten** aus der Gegenrichtung (asymmetrisch möglich),
  `backwardTravelTime` separat, `sourceSymmetry/targetSymmetry` aus den Zeiten
  abgeleitet. Ohne Gegenrichtung → `one_way`.
- `consecutiveTime` = absolute Minuten → Fahrzeiten > 60' korrekt.
- **Taktschätzung** am Referenztag (Standard: Dienstag in der Mitte der
  Fahrplanperiode, `--day` ändert): ≥ 12 Stunden zwischen 6 und 21 Uhr → 60',
  nur gerade/ungerade Stunden → 120 / 120+, gehäuft in HVZ → HVZ, sonst
  „zeitweise". Gleiche Fahrzeit um 30/20/15' versetzt → 30'/20'/15'-Takt.
- `numberOfStops` = Halte zwischen zwei Knoten, die nicht in der Region sind.
- **Taktfahrten** (`*Z` mit Anzahl/Taktzeit) werden expandiert.
- **Validierung** vor dem Schreiben: verwaiste Ports/Transitions, falsche
  Port-Referenzen, doppelte IDs/Kürzel, Metadaten-Referenzen, Zeitbereiche.

## Spec-Format (`spec.json`)

```json
{"name": "Neuenburg",
 "positions": {"NE": [0, 0]},
 "trainruns": [
  {"name": "66 BN-CF", "category": "IR", "frequency": "60", "timeCategory": "7/24",
   "direction": "round_trip",
   "stops": [{"at": "BN", "dep": 793}, {"at": "KZ", "arr": 810, "dep": 811},
             {"at": "NE", "arr": 828, "dep": 829, "skipped": 1}, {"at": "CF", "arr": 857}],
   "back":  [{"at": "CF", "dep": 843}, {"at": "NE", "arr": 871, "dep": 872},
             {"at": "KZ", "arr": 889, "dep": 890}, {"at": "BN", "arr": 907}]},
  {"name": "Variante", "skip": true, "stops": []}
 ]}
```

Zeiten in Minuten ab Mitternacht (Werte > 59 erlaubt, nur die Differenzen und
`mod 60` zählen). `back` ist optional (sonst Spiegelung an Minute 0), `pass: true`
markiert eine Durchfahrt, `skip: true` lässt eine Linie weg.
Kategorien: `EC IC IR RE S GEX G`; Takte: `15 20 30 60 120 120+`;
Zeitkategorien: `7/24 HVZ zeitweise`. `examples/spec_example.json` läuft ohne Downloads.

## Grenzen (ehrlich)

- `suggest` liefert einen **Entwurf**. Linienvarianten, Abschnitte am
  Regionsrand und Sonderzüge brauchen weiterhin den Quercheck gegen die
  SMA-Netzgrafik.
- Linien werden an der Region abgeschnitten; Knoten ohne Halt (Abzweigungen)
  kommen nur vor, wenn sie in HRDF als Halt/Durchfahrt stehen.
- Die Spaltennamen der atlas-CSV werden über Aliase erkannt (`didok.py`); ändert
  das BAV/SBB das Format, bricht `stations` mit der Liste der vorhandenen Spalten
  ab → Alias ergänzen.
- Verkehrstage: Bit 0 des HRDF-Bitfelds = erster Tag aus `ECKDATEN`. Mit
  `--all-days` wird nicht gefiltert.
- Port-Reihenfolge bei parallelen Linien: NGE ordnet beim Laden selbst neu
  (Greedy-Heuristik), Kreuzungen sind kein Datenfehler.

## Tests

```bash
python -m unittest discover -s tests -v
```

Die Tests erzeugen ein kleines, formatgetreues HRDF-ZIP und eine atlas-CSV
(`tests/make_fixtures.py`) und prüfen den ganzen Weg bis zur validen NGE-Datei,
inkl. Taktfahrten, Bitfeldern, LINIE-Verweisen, Durchfahrten und asymmetrischer
Rückfahrt.

### Gegenprobe im echten Netzgrafik-Editor

```bash
tools/check_in_nge.sh netzgrafik.json      # klont NGE, laedt die Datei mit DataService.loadNetzgrafikDto
```

Prueft, dass NGE die Datei ohne Fehler laedt, alle Ports/Transitions aufloest
und die Minuten nach dem Laden unveraendert bleiben (Node 20+, Chrome noetig).

## Lizenzen

Code: MIT. `nge_fahrplan/metadata_default.json` stammt aus netzgrafik-editor-frontend
(Apache-2.0, © SBB / OpenRail Association). Daten: opendata.swiss, Nutzungsbedingung
„Quellenangabe" (opentransportdata.swiss).
