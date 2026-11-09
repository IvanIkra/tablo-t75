#!/bin/sh
# Build the order package for pcb/tablo.kicad_pcb in pcb/fab/:
#   fab/tablo-order/         Gerbers + drill, BOM with part numbers, pick-and-place, assembly drawing,
#                            schematic, ODB++, STEP, the same for the assembly panel, the KiCad project
#   fab/tablo-order.zip      all of it in one archive
# Needs kicad-cli and KiCad's Python (for pcbnew). See pcb/order-notes.md for what goes to the board house.
set -eu
cd "$(dirname "$0")/.."
KICAD_CLI="${KICAD_CLI:-kicad-cli}"
KPY="${KPY:-/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3}"
OUT=fab/tablo-order
rm -rf fab
mkdir -p "$OUT/panel" "$OUT/kicad" fab/tmp

quiet() { "$@" 2>&1 | grep -v -e 'Fontconfig' -e 'swig/python' -e 'assert ""traits""' || true; }

gerbers() {  # board.kicad_pcb out.zip
  dir=fab/tmp/$(basename "$2" .zip)
  mkdir -p "$dir"
  quiet "$KICAD_CLI" pcb export gerbers --output "$dir/" \
    --layers F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
    --subtract-soldermask --no-x2 --use-drill-file-origin "$1"
  quiet "$KICAD_CLI" pcb export drill --output "$dir/" --format excellon --excellon-separate-th \
    --drill-origin plot --generate-map --map-format gerberx2 "$1"
  (cd "$dir" && zip -q "$OLDPWD/$2" ./*)
}

assembly_pdf() {  # board.kicad_pcb out.pdf
  quiet "$KICAD_CLI" pcb export pdf --mode-single --layers F.Fab,Edge.Cuts --scale 0 --exclude-value \
    --crossout-DNP-footprints-on-fab-layers --black-and-white --output "$2" "$1"
}

# single board
gerbers tablo.kicad_pcb "$OUT/tablo-gerbers.zip"
quiet "$KPY" tools/order_package.py bom tablo.kicad_pcb bom-parts.csv "$OUT/tablo-bom.csv"
quiet "$KPY" tools/order_package.py pos tablo.kicad_pcb "$OUT/tablo-pos.csv"
assembly_pdf tablo.kicad_pcb "$OUT/tablo-assembly.pdf"
quiet "$KICAD_CLI" sch export pdf --output "$OUT/tablo-schematic.pdf" tablo.kicad_sch
quiet "$KICAD_CLI" pcb export odb --output "$OUT/tablo-odb.zip" tablo.kicad_pcb
quiet "$KICAD_CLI" pcb export step --output "$OUT/tablo.step" --subst-models --no-dnp tablo.kicad_pcb

# assembly panel
quiet "$KPY" tools/order_package.py panel tablo.kicad_pcb fab/tmp/tablo-panel.kicad_pcb
cp tablo.kicad_pro fab/tmp/tablo-panel.kicad_pro
gerbers fab/tmp/tablo-panel.kicad_pcb "$OUT/panel/tablo-panel-gerbers.zip"
quiet "$KPY" tools/order_package.py pos fab/tmp/tablo-panel.kicad_pcb "$OUT/panel/tablo-panel-pos.csv"
assembly_pdf fab/tmp/tablo-panel.kicad_pcb "$OUT/panel/tablo-panel-assembly.pdf"
quiet "$KICAD_CLI" pcb export odb --output "$OUT/panel/tablo-panel-odb.zip" fab/tmp/tablo-panel.kicad_pcb

# KiCad project and the notes
cp -R tablo.kicad_pro tablo.kicad_sch tablo.kicad_pcb tablo.kicad_sym tablo.pretty sym-lib-table fp-lib-table "$OUT/kicad/"
cp order-notes.md "$OUT/README.md"
rm -rf fab/tmp
(cd fab && zip -qr tablo-order.zip tablo-order)
echo "written: fab/tablo-order.zip"
(cd "$OUT" && find . -type f | sort)
