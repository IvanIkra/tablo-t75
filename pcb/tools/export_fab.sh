#!/bin/sh
# Export manufacturing files for pcb/tablo.kicad_pcb into pcb/fab/:
# Gerbers and drill files (zipped for the board house), a pick-and-place file
# for the parts on F.Cu and a BOM grouped by value and footprint.
set -eu
cd "$(dirname "$0")/.."
KICAD_CLI="${KICAD_CLI:-kicad-cli}"
rm -rf fab
mkdir -p fab/gerbers
"$KICAD_CLI" pcb export gerbers --output fab/gerbers/ \
  --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
  --subtract-soldermask --no-x2 tablo.kicad_pcb
"$KICAD_CLI" pcb export drill --output fab/gerbers/ --format excellon --excellon-separate-th \
  --generate-map --map-format gerberx2 tablo.kicad_pcb
(cd fab/gerbers && zip -q ../tablo-gerbers.zip ./*)
"$KICAD_CLI" pcb export pos --output fab/tablo-pos-front.csv --format csv --units mm --side front \
  --exclude-dnp tablo.kicad_pcb
"$KICAD_CLI" sch export bom --output fab/tablo-bom.csv \
  --fields 'Reference,Value,Footprint,${QUANTITY}' --group-by 'Value,Footprint' \
  --exclude-dnp tablo.kicad_sch
echo "written: $(ls fab)"
