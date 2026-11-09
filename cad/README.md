# Tablo T75 — enclosure: printing and assembly

The model is `tablo.scad`, parametric, OpenSCAD 2026+. The STLs are in `stl/`, the previews in `preview/`.
To rebuild a part: `openscad --backend=manifold -o stl/tablo-front.stl -D 'part="front"' tablo.scad`

The enclosure is 185 × 146 × 17 mm and flat: it hangs on the wall on two screws or, without drilling, on the T-shaped `wall_mount` bar glued to the wall. For the desk there is a back leg like a photo frame's: it hooks into the same holes, holds the screen at 15° and is not visible from the front.
Chamfers are 1.5 mm on the front edge, 1 mm on the cover edge and 0.5 mm on the key cut-outs (the `front_chamfer`, `back_chamfer`, `pill_chamfer` parameters; 0 means no chamfer).

## What is inside

| Part | Size | Where the dimensions come from |
|---|---|---|
| Screen Good Display GDEY075T7 | 170.2 × 111.2 × 1.25, active area 163.2 × 97.92 | the drawing from good-display.com |
| Board ESP32-L(C02) | 70 × 54 | the buy-lcd.com page; the Type-C and switch positions from photos, **to measure** |
| Adapter DESPI-C02 | 41 × 22 | the same |
| 8 × Kailh Choc v1 Brown | 1.3 mm plate, 13.8 cut-out | heights above the plate are estimates, **check on the key test** |

## What else to buy

| What | How many | What for |
|---|---|---|
| M2.5×3×4 heat-set insert | 7 | 4 in the enclosure's corner bosses, 3 in the block under the keys |
| M2.5×8 countersunk screw, DIN 965 | 4 | the back cover |
| M2.5×6 cylinder-head screw (Torx) | 3 | the switch plate (the plate has 1.7 mm pads under the heads, so the screw ends right in the insert) |
| Thin double-sided tape, 0.5 mm | ~0.5 m | the screen to the frame, the adapter to its pad |
| 30 AWG wire | ~1 m | buttons → board, adapter → board |
| A thin rubber strip / 2 feet | — | on the enclosure's bottom end and the leg's foot, against slipping (optional) |
| Two wood screws (Ø4, head ≤ 8.5 mm) | 2 | for the wall; in the leg, printed `peg` mushrooms are glued in instead of screws |
| Superglue or epoxy | a drop | to glue the pegs into the leg |
| Double-sided foam tape (3M VHB or Command) | ~0.4 m of a 19–25 mm strip | the `wall_mount` bar to the wall |
| A USB-C cable, preferably with a right-angle plug | 1 | power, entering from the side |

## Printing

| File | Qty | Orientation | Notes |
|---|---|---|---|
| `tablo-key_test.stl` | 1 | as is | **print first**, see below |
| `tablo-front.stl` | 1 | face down | no supports; the switch pockets are short bridges |
| `tablo-key_plate.stl` | 1 | flat | 1.3 mm, 100% infill |
| `tablo-back.stl` | 1 | outside down | no supports; the keyhole channels are a 9.5 mm bridge |
| `tablo-leg.stl` | 1 | bar down (as exported) | no supports, the rib prints as a vertical wall |
| `tablo-wall_mount.stl` | 1 | wall side down (as exported) | no supports; 124 × 120 × 5 mm, 4 perimeters, the pegs print together with the bar: a 0.5 mm step and a 45° cone under the head — a mount without drilling |
| `tablo-peg.stl` | 1 (2 pegs) | head down (as exported) | 100% infill; the Ø2.9 stem is glued into the bar's Ø3.2 hole up to the step, with a groove along the stem for air and extra glue |
| `tablo-keycap.stl` | 7 | top down | 0.12 layers, the stems are thin |
| `tablo-keycap_dimple.stl` | 1 | top down | the "all off" key with a dimple |

PLA or PETG, 0.2 mm layers, 3 perimeters.

## Before printing the enclosure — measure and fit

1. **The key test (`key_test`).** Put a switch into the test plate, hold it against the test wall and fit a keycap.
   - The switch should snap into the plate without play. If it wobbles or will not go in — `choc_cut`.
   - The keycap should sit flush with the test's front and travel the full stroke without catching. Tune with `stem_top_rest` and `house_above_plate`.
   - The keycap should sit tight on the stems. If not — `stem_w` / `stem_dx`.
2. **The ESP32-L board** (after desoldering the sockets):
   - the height of the tallest component above the board → `comp_h`;
   - the centre of the Type-C from the bottom edge of the board → `usbc_from_bottom`;
   - the power switch → `switch_from_bottom`.
3. **The screen.** Check that the FPC comes out at the bottom, its centre 79.9 mm from the right edge, looking at the screen from the front → `fpc_from_right`.

All these parameters are at the top of `tablo.scad`.

## Assembly

1. **The board.** Desolder the yellow sockets and the black 8-pin P5 socket from the ESP32-L. Leave the Type-C, the reset button and the switch. Clip the pins on the back flush.
2. **The adapter.** Connect the DESPI-C02 to the P5 pads with eight wires: BUSY, RES, D/C, CS, SCK, SDI, GND, 3.3 V.
3. **The screen.** Run thin tape around the window frame on the inside of the front. Lay the screen between the guides, active side to the window, FPC down, and press it in. Bend the FPC back, behind the screen.
4. **The buttons.** Melt 3 inserts into the holes under the keys and 4 into the corner bosses with a soldering iron (~220 °C). Snap 8 switches into the plate (from the keycap side), put the plate into the pockets from the inside and fasten it with 3 M2.5×6 screws.
5. **Button wires.** One pin of each switch goes to a common GND, the other to its own GPIO.
6. **The cover.** Stick the adapter to the cover's pad and plug the screen's FPC into its connector. Snap the board into the cover's clips, components facing the cover: the Type-C edge towards the cut-outs in the side wall.
7. **Closing.** Close the cover and drive in 4 M2.5×8 countersunk screws. Fit the keycaps; the "all off" one with the dimple goes leftmost, seen from the front.
8. **The desk leg.** Glue two pegs (`tablo-peg.stl`) into the holes on the leg's bar until the step meets the bar — then the head stands exactly 2.8 mm out. Wipe extra glue off the step and let it set. Put the heads into the wide part of the wall holes and slide the leg up until it clicks into the narrow part. The enclosure stands on its bottom end and leans on the leg; its own weight keeps the pegs in the lock. For the wall the leg simply comes off.
9. **The wall bar (no drilling).** The bar has its own pegs, printed with it. Degrease the wall with alcohol and stick tape in strips along the crossbar and the leg of the T on the bar's smooth side. Press the bar to the wall level (the top edge is straight, the notch marks at the top and bottom are for vertical) and hold for 30 s; hang the enclosure preferably after a day, once the tape is at full strength. Put the enclosure on the pegs by the wide parts of its holes and lower it 8 mm into the lock. The top of the bar is 2 mm below the top of the enclosure and the leg of the T rests against the cover from below, so the enclosure hangs parallel to the wall 5 mm off it and the bar is not visible from the front.

## For the custom board

The STLs in `stl/` are for the ESP32-L kit that is in the enclosure now. For Tablo's own board ([`../pcb/`](../pcb/README.md)) build the front and the back cover with `-D 'board="custom"'`:

```bash
openscad --backend=manifold -o stl/tablo-front-custom.stl -D 'part="front"' -D 'board="custom"' tablo.scad
openscad --backend=manifold -o stl/tablo-back-custom.stl -D 'part="back"' -D 'board="custom"' tablo.scad
```

What changes with the custom board:

- **Front:** the USB-C opening moves to the board's height (36 mm from the bottom) and opens to the back edge, because the receptacle sits 13.3 mm deep, close to the cover; the slot for the power switch is 19 mm from the bottom. The thicker wall at the old ports goes away.
- **Back cover:** no board clips and no adapter pad. Instead there is a fence for the 604060 LiPo (lying on the cover behind the screen), three posts between the keys that keep the board on the switches, 1 mm pockets over the ESP32 module and the USB-C receptacle, and vent slots over the charger.
- The board hangs on the 8 switches: they clip into the plate and their pins are soldered into the board. Its front face is `plate_z0 + plate_t + below_plate` (10.1 mm) from the front of the enclosure, so `below_plate` has to be checked against the real switch before the board is ordered.

## Not covered yet

- The ESP32-L board's holes are not used: their position is unknown, and the board is held by clips. With the board at hand, standoffs for screws can be added.
- The keycap travel is calculated from estimated Choc v1 dimensions, so the key test must be printed first.

## What is verified and what is an estimate

Carried over from the notes of 14–15.10.2026. The "Estimate" column is to be checked before printing the enclosure.

| Exact (from sources) | Estimate — to check |
|---|---|
| GDEY075T7 dimensions from the manufacturer's drawing: 170.2×111.2×1.25; active area 163.2×97.92; 3.49 top margin; FPC at the bottom, centre 79.9 mm from the right edge, 12.5 wide, 24 long | Choc v1 heights above the plate (`stem_top_rest` 4.6, `house_above_plate` 1.8), keycap stems (1.15×3, 5.7 pitch) |
| ESP32-L 70×54, DESPI-C02 41×22, 5 V power | The Type-C position (32.5 mm from the bottom of the board) and the switch (13.8 mm) — from photos |
| Board: Type-C and the switch on the short edge | Component height after desoldering (`comp_h` = 5) |
| Fasteners: M2.5×3×4 inserts, M2.5×8 countersunk, M2.5×6 Torx | The insert hole diameter, 3.6 mm |
| All STLs build without errors | Stability on the leg, the wall-hole lock (`screw_gap` 2.8) |
