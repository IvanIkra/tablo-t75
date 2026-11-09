# Tablo main board — order notes

One board, assembled on the top side only. Everything needed to make and assemble it is in this
package; the KiCad project is included as well.

## Board

| | |
|---|---|
| Size | 173.5 × 41.6 mm (single board); 173.5 × 70.6 mm as an assembly panel (`panel/`) |
| Layers | 4: F.Cu (signals), In1.Cu (GND plane), In2.Cu (3.3 V plane), B.Cu (signals) |
| Thickness | 1.6 mm (1.5 mm is fine) |
| Material | FR-4, Tg 150 or higher |
| Copper | outer 35 µm (1 oz), inner 18–35 µm |
| Min track / space | 0.15 / 0.15 mm |
| Min hole | 0.3 mm (vias 0.3 mm drill, 0.6 mm pad) |
| Slots | plated oval holes for the USB-C shell (0.6 × 1.2 and 0.6 × 1.7 mm) |
| Cut-out | one milled slot 14 × 2 mm inside the board (the screen's FPC goes through it) |
| Surface finish | ENIG (immersion gold): 0.5 mm pitch QFN/DFN parts |
| Solder mask | green, both sides; vias tented |
| Silkscreen | white, top (bottom has a few labels) |
| Electrical test | yes |
| Origin | all files use the board's bottom-left corner as 0,0 (the panel's bottom-left corner in `panel/`) |

Gerber files (`*-gerbers.zip`): `F_Cu`, `In1_Cu`, `In2_Cu`, `B_Cu`, `F_Mask`, `B_Mask`, `F_Paste`
(stencil, top), `F_Silkscreen`, `B_Silkscreen`, `Edge_Cuts` (outline and the inner slot); drill files
in Excellon, plated and non-plated separately, with a drill map.

## Assembly

- **Top side only**, 64 parts on 31 BOM lines, ~270 paste apertures. Pick-and-place: `tablo-pos.csv`
  (mm, rotation in degrees counter-clockwise as seen from the top).
- **Not fitted (DNP):** SW1–SW8 (key switches), J2 (battery lead pads), TP1–TP6 (test pads). They
  are marked DNP in the BOM and crossed out in `tablo-assembly.pdf`. The key switches are soldered
  by hand after assembly.
- **Fine pitch / bottom pads:** U2 BQ24074 (VQFN-16 3 × 3 mm), U3 MAX17048 (TDFN-8 2 × 2 mm),
  U4 TPS63802 (VSON-HR-10 2 × 3 mm) — their exposed pads must be soldered; J3 FPC connector 0.5 mm.
- **J3 must be the top-contact version** (Hirose FH12A-24S-0.5SH(55)), not the bottom-contact FH12: the
  screen's FPC reaches it with its contacts facing up. Both use the same land pattern.
- **ESP32 module** (U1): moisture-sensitive (MSL 3), bake if the bag was open.
- **Through-hole:** only the USB-C shell pegs (J1), soldered with the rest if possible.
- **Fiducials:** three on the board (FID1–FID3, 1 mm copper in a 2 mm mask opening), three more on
  the panel rails.
- Lead or lead-free paste, no-clean flux; no washing or coating needed.
- Parts: the BOM lists a manufacturer part number for every line; where the Notes column says so,
  an equivalent part is fine.

## Panel (`panel/`)

For assembly lines that need boards of 70 × 70 mm or more: one board with a 12.5 mm rail along each
long edge, joined by three 5 mm tabs per side with mouse bites (0.5 mm holes), 2 mm milled channels,
three fiducials and four 2 mm tooling holes on the rails. Break off the rails after assembly.

## Files

| File | What |
|---|---|
| `tablo-gerbers.zip` | Gerbers and drill files of the single board |
| `tablo-bom.csv` | BOM with manufacturer part numbers and DNP lines |
| `tablo-pos.csv` | Pick-and-place, top side, fitted parts only |
| `tablo-assembly.pdf` | Assembly drawing: part outlines and designators, DNP crossed out |
| `tablo-schematic.pdf` | Schematic |
| `tablo-odb.zip` | ODB++ of the board |
| `tablo.step` | 3D model of the board |
| `panel/` | The same for the assembly panel (Gerbers, pick-and-place, assembly drawing, ODB++) |
| `kicad/` | KiCad 10 project (schematic, board, project-specific symbols and footprints) |
