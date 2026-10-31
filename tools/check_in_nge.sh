#!/usr/bin/env bash
# Laedt zwei erzeugte Dateien im echten NGE-Code (DataService.loadNetzgrafikDto)
# und prueft Ports/Transitions/Zeiten nach dem Laden. Braucht Node 20+ und Chrome.
#   tools/check_in_nge.sh netz_a.json [netz_b.json]
set -euo pipefail
A=$(realpath "$1"); B=$(realpath "${2:-$1}")
DIR=${NGE_DIR:-.nge-frontend}
[ -d "$DIR" ] || git clone --depth 1 https://github.com/OpenRailAssociation/netzgrafik-editor-frontend.git "$DIR"
cp "$A" "$DIR/src/integration-testing/test-data/nge_fahrplan_a.json"
cp "$B" "$DIR/src/integration-testing/test-data/nge_fahrplan_b.json"
cp "$(dirname "$0")/nge-fahrplan-import.test.spec.ts" "$DIR/src/integration-testing/"
cd "$DIR"
[ -d node_modules ] || npm ci --no-audit --no-fund
npx ng test -c ci --include src/integration-testing/nge-fahrplan-import.test.spec.ts
