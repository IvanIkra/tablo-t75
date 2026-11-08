# Tablo main board

KiCad 10 project for Tablo's own board: ESP32-S3 module, LiPo charger and fuel gauge, 3.3 V buck-boost, the e-paper booster circuit and the 8 key switches on one long board. The design notes, parts and pin map are in [`../docs/hardware.md`](../docs/hardware.md#custom-board-in-design).

Status: first draft of the schematic, ERC clean; no layout yet.

| File | What |
|---|---|
| `tablo.kicad_sch` | The schematic (one A3 sheet, nets joined by labels) |
| `tablo.kicad_sym` | Parts missing from the KiCad libraries: TPS63802, MAX17048 |
| `tablo.pretty/` | Footprints missing from the KiCad libraries; to be drawn with the layout: `Kailh_Choc_V1`, `Texas_DLA0010A_VSON-HR-10_2x3mm` |
| `tools/gen_schematic.py` | Generated the first draft of the schematic and `tablo.kicad_sym` from the KiCad libraries |

The script only bootstrapped the schematic. After the schematic is edited in KiCad, edit it there and do not re-run the script, or the edits are lost.

Check the schematic:

```bash
kicad-cli sch erc --severity-all pcb/tablo.kicad_sch
```

Warnings about missing libraries only mean that KiCad's global library tables are not set up yet (KiCad does that on first start).
