# Tablo main board

KiCad 10 project for Tablo's own board: ESP32-S3 module, LiPo charger and fuel gauge, 3.3 V buck-boost, the e-paper booster circuit and the 8 key switches on one long board. The design notes, parts and pin map are in [`../docs/hardware.md`](../docs/hardware.md#custom-board-in-design); the matching enclosure is `board = "custom"` in [`../cad/`](../cad/README.md#for-the-custom-board).

Status: the schematic passes ERC; the layout is fully routed and passes DRC with the schematic parity check (left: silkscreen warnings and four thermal reliefs with one spoke). Not ordered, nothing is tried on hardware yet; see "Before ordering" below.

DRC also shows silkscreen warnings (labels over pads and the board edge) and four thermal reliefs with one spoke; none of them affects the copper.

| File | What |
|---|---|
| `tablo.kicad_sch` | The schematic (one A3 sheet, nets joined by labels) |
| `tablo.kicad_pcb` | The board: 173.5 × 41.6 mm, 4 layers (signals on F.Cu and B.Cu, solid planes: GND on In1, 3.3 V on In2) |
| `tablo.kicad_sym` | Parts missing from the KiCad libraries: TPS63802, MAX17048 |
| `tablo.pretty/` | Footprints missing from the KiCad libraries: `Kailh_Choc_V1`, `Texas_DLA0010A_VSON-HR-10_2x3mm` (from the TPS63802 datasheet's example layout) |
| `tools/` | The scripts that produced the drafts, the Freerouting round trip, and the export of the manufacturing files |

## How the drafts were made

The scripts only bootstrap the design. Once a file is edited by hand in KiCad, edit it there and do not re-run the script that wrote it, or the edits are lost.

```bash
# schematic and the custom symbols
python3 pcb/tools/gen_schematic.py
# netlist -> board: outline from the enclosure, placement, planes
kicad-cli sch export netlist --format kicadsexpr -o tablo.net pcb/tablo.kicad_sch
KPY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KPY pcb/tools/gen_board.py build tablo.net
# routing: a small grid router (A* on a 0.05 mm grid; F.Cu, B.Cu and In2 when needed; vias to the planes)
$KPY pcb/tools/gen_board.py export geom.json
uv run --no-project --with numpy --with scipy python pcb/tools/route.py geom.json routes.json short
$KPY pcb/tools/gen_board.py apply routes.json
```

The router routes the signals of the fine-pitch parts first, then the power nets, then the rest; what fails gets a second pass with cheaper vias and a rip-up of the nets in its way (undone if they cannot be routed again), and GND and 3.3 V pads get short stubs to vias into the planes. `route.py finish geom.json routes.json out.json NET:REF.NUM ...` keeps a result and only tries the listed connections again. Each run takes about 10 minutes; the order (`short` or `long`) changes the result, so it is worth running both.

That draft left three connections open (around the FPC connector, where PREVGH and PREVGL boxed in VSH1 and VSL, and a piece of the 3.3 V plane cut off by tracks on In2). The committed board is that draft with part of it rerouted by [Freerouting](https://github.com/freerouting/freerouting) 2.5.0: the nets around the FPC and every net that had tracks on In2 were taken out and routed again on F.Cu and B.Cu only, so both inner layers are now solid planes. Freerouting necks power tracks down near pads and keeps only the track clearance from the FPC slot, so the script grows the slot's keepout and widens the power segments back afterwards:

```bash
$KPY pcb/tools/freeroute.py export pcb/tablo.kicad_pcb board.dsn /EPD_PREVGH /EPD_PREVGL /EPD_VSH1 /EPD_VSL \
    /VBAT /VSYS /BTN3 /BTN8 /USB_DP /USB_DN /BAT_ALRT_N /EPD_3V3 /XTAL32_P /EPD_SCK /EPD_MOSI
java -Djava.awt.headless=true -jar freerouting-2.5.0.jar -de board.dsn -do board.ses \
    --router.autorouter.max_passes=200 -mt 1 --router.copper_to_edge_clearance_um=300 \
    --gui.enabled=false --api_server.enabled=false --usage_and_diagnostic_data.disable_analytics=true
$KPY pcb/tools/freeroute.py import pcb/tablo.kicad_pcb board.ses routed.kicad_pcb
$KPY pcb/tools/freeroute.py widen routed.kicad_pcb pcb/tablo.kicad_pcb
```

Freerouting 2.5.0 needs Java 25 or newer (Homebrew's `openjdk` works); its native macOS CLI build crashes on this board. Routing the whole board from scratch with Freerouting left 16–40 connections open, so it is used only to finish.

`gen_board.py` takes the enclosure's numbers (key pitch, panel and FPC position) so that the board matches `cad/tablo.scad`: board coordinates are the enclosure's seen from the back, X = x and Y = 146 − y.

## Checks and manufacturing files

```bash
kicad-cli sch erc --severity-all pcb/tablo.kicad_sch
kicad-cli pcb drc --schematic-parity pcb/tablo.kicad_pcb
pcb/tools/export_fab.sh      # Gerbers + drill (zipped), pick-and-place, BOM into pcb/fab/
```

Warnings about missing libraries only mean that KiCad's global library tables are not set up yet (KiCad does that on first start).

## Before ordering

- **Print the board 1:1 and try the real parts on it:** the Choc footprint (pin positions and the side the pins are on), the FPC connector against the panel's FPC (contact side and pin 1 — the FPC passes through the slot), the USB-C and the power switch at the enclosure's openings.
- **Measure `below_plate`** on a real switch: it sets how deep the board sits and how much room the parts have under the cover.
- **Review the power layout by eye:** both routers are generic. The loops of the TPS63802 (input cap, inductor, output cap) and of the e-paper booster (inductor, MOSFET, RESE resistor, diodes) should be short and on one layer; move parts and reroute by hand where they are not.
- **Pick the exact parts for assembly** (LCSC numbers for the board house's BOM): the 0.47 µH and 10 µH inductors, the 32.768 kHz crystal and its load capacitors, the slide switch, the FPC connector.
