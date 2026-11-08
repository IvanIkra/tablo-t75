"""Generate the first Tablo board schematic (pcb/tablo.kicad_sch).

Every symbol pin gets a short wire and a net label, so the whole sheet is
connected by labels. Symbols come from the KiCad libraries installed with
KiCad; TPS63802 and MAX17048 come from pcb/tablo.kicad_sym, written here too.

This script bootstraps the schematic. Once it is edited by hand in KiCad,
edit the schematic directly instead of re-running the script.

Run:  python3 pcb/tools/gen_schematic.py [path/to/kicad/symbols]
"""

import copy
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from sexpr import Q, dump, find, find_all, parse  # noqa: E402

PCB = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SYMDIR = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "KICAD_SYMBOL_DIR", "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
VERSION = "20251024"
NS = uuid.UUID("6f1c7d1e-6a43-4a57-9d3a-7ab10a7b0075")


def uid(*parts):
    return Q(str(uuid.uuid5(NS, "/".join(map(str, parts)))))


ROOT = uid("root")

# ---------------------------------------------------------------- custom library


def _font():
    return ["effects", ["font", ["size", "1.27", "1.27"]]]


def _prop(name, value, x, y, hide=False):
    p = ["property", Q(name), Q(value), ["at", x, y, 0]]
    if hide:
        p.append(["hide", "yes"])
    p.append(_font())
    return p


def _pin(kind, x, y, ang, name, num):
    return ["pin", kind, "line", ["at", x, y, ang], ["length", "2.54"],
            ["name", Q(name), _font()], ["number", Q(num), _font()]]


def custom_symbol(name, ref, footprint, datasheet, desc, half_w, half_h, pins):
    body = ["symbol", Q(name + "_0_1"),
            ["rectangle", ["start", -half_w, half_h], ["end", half_w, -half_h],
             ["stroke", ["width", "0.254"], ["type", "default"]], ["fill", ["type", "background"]]]]
    unit = ["symbol", Q(name + "_1_1")] + [_pin(*p) for p in pins]
    return ["symbol", Q(name), ["pin_names", ["offset", "1.016"]],
            ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            _prop("Reference", ref, 0, half_h + 1.27),
            _prop("Value", name, 0, -half_h - 1.27),
            _prop("Footprint", footprint, 0, -half_h - 3.81, True),
            _prop("Datasheet", datasheet, 0, -half_h - 6.35, True),
            _prop("Description", desc, 0, -half_h - 8.89, True),
            body, unit]


CUSTOM = [
    custom_symbol(
        "TPS63802", "U", "tablo:Texas_DLA0010A_VSON-HR-10_2x3mm",
        "https://www.ti.com/lit/ds/symlink/tps63802.pdf",
        "2 A buck-boost converter, 11 uA quiescent, VSON-HR-10 2x3 mm", 7.62, 7.62, [
            ("power_in", -10.16, 5.08, 0, "VIN", "10"),
            ("input", -10.16, 2.54, 0, "EN", "1"),
            ("input", -10.16, 0, 0, "MODE", "2"),
            ("passive", -10.16, -2.54, 0, "L1", "9"),
            ("power_in", -10.16, -5.08, 0, "GND", "8"),
            ("power_out", 10.16, 5.08, 180, "VOUT", "6"),
            ("input", 10.16, 2.54, 180, "FB", "4"),
            ("open_collector", 10.16, 0, 180, "PG", "5"),
            ("passive", 10.16, -2.54, 180, "L2", "7"),
            ("power_in", 10.16, -5.08, 180, "AGND", "3"),
        ]),
    custom_symbol(
        "MAX17048", "U", "Package_DFN_QFN:TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm",
        "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX17048-MAX17049.pdf",
        "1-cell Li-ion fuel gauge with ModelGauge, I2C, TDFN-8 2x2 mm", 7.62, 10.16, [
            ("power_in", -10.16, 5.08, 0, "VDD", "3"),
            ("input", -10.16, 2.54, 0, "CELL", "2"),
            ("input", -10.16, -2.54, 0, "CTG", "1"),
            ("input", -10.16, -5.08, 0, "QSTRT", "6"),
            ("bidirectional", 10.16, 5.08, 180, "SDA", "8"),
            ("input", 10.16, 2.54, 180, "SCL", "7"),
            ("open_collector", 10.16, -2.54, 180, "~{ALRT}", "5"),
            ("power_in", 10.16, -5.08, 180, "GND", "4"),
            ("passive", 10.16, -7.62, 180, "EP", "9"),
        ]),
]

# ---------------------------------------------------------------- library access

_libs = {}


def lib_symbol(lib, name):
    """Flattened library symbol (extends resolved), as a parsed list."""
    if lib not in _libs:
        if lib == "tablo":
            _libs[lib] = {x[1]: x for x in CUSTOM}
        else:
            tree = parse(open(os.path.join(SYMDIR, lib + ".kicad_sym"), encoding="utf-8").read())[0]
            _libs[lib] = {x[1]: x for x in find_all(tree, "symbol")}
    sym = copy.deepcopy(_libs[lib][name])
    ext = find(sym, "extends")
    if ext:
        parent = lib_symbol(lib, ext[1])
        child_props = {p[1]: p for p in find_all(sym, "property")}
        out = [sym[0], Q(name)]
        for item in parent[2:]:
            if isinstance(item, list) and item[0] == "property" and item[1] in child_props:
                out.append(child_props.pop(item[1]))
            elif isinstance(item, list) and item[0] == "symbol":
                item[1] = Q(item[1].replace(ext[1], name, 1))
                out.append(item)
            else:
                out.append(item)
        out[2:2] = list(child_props.values())
        sym = out
    return sym


def pins_of(sym):
    """[(number, x, y, angle, type)] for unit 1 / common pins."""
    out = []
    for sub in find_all(sym, "symbol"):
        unit = sub[1].rsplit("_", 2)[-2]
        if unit not in ("0", "1"):
            continue
        for p in find_all(sub, "pin"):
            at = find(p, "at")
            out.append((find(p, "number")[1], float(at[1]), float(at[2]), int(float(at[3])), p[1]))
    return out


# ---------------------------------------------------------------- sheet building

used_libs = {}
items = []          # schematic items after lib_symbols
refs_seen = set()
OUT = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}   # outward direction in sheet coords
LABEL_ANG = {(-1, 0): 180, (1, 0): 0, (0, 1): 270, (0, -1): 90}
STUB = 2.54


def r2(v):
    return round(v, 4)


def snap(v):
    """Keep symbols on the 1.27 mm connection grid."""
    return r2(round(v / 1.27) * 1.27)


def label(net, x, y, d):
    ang = LABEL_ANG[d]
    just = "right" if ang in (180, 270) else "left"
    items.append(["label", Q(net), ["at", r2(x), r2(y), ang],
                  ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", just, "bottom"]],
                  ["uuid", uid("label", net, x, y)]])


def wire(x1, y1, x2, y2):
    items.append(["wire", ["pts", ["xy", r2(x1), r2(y1)], ["xy", r2(x2), r2(y2)]],
                  ["stroke", ["width", "0"], ["type", "default"]], ["uuid", uid("wire", x1, y1, x2, y2)]])


def text(s, x, y, size=2.0):
    items.append(["text", Q(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
                  ["effects", ["font", ["size", size, size], ["bold", "yes"]], ["justify", "left", "bottom"]],
                  ["uuid", uid("text", s, x, y)]])


def note(s, x, y):
    items.append(["text", Q(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
                  ["effects", ["font", ["size", "1.27", "1.27"]], ["justify", "left", "top"]],
                  ["uuid", uid("note", s, x, y)]])


def place(lib_id, ref, value, x, y, nets, footprint=None, datasheet=None, nc_ok=True):
    """Place a symbol at (x, y) and label its pins from nets {pin number: net}."""
    x, y = snap(x), snap(y)
    lib, name = lib_id.split(":")
    sym = lib_symbol(lib, name)
    if lib_id not in used_libs:
        top = copy.deepcopy(sym)
        top[1] = Q(lib_id)
        used_libs[lib_id] = top
    assert ref not in refs_seen, ref
    refs_seen.add(ref)
    is_power = find(sym, "power") is not None
    inst = ["symbol", ["lib_id", Q(lib_id)], ["at", x, y, 0], ["unit", 1],
            ["exclude_from_sim", "no"], ["in_bom", "no" if is_power else "yes"], ["on_board", "yes"],
            ["dnp", "no"], ["uuid", uid("sym", ref)]]
    for p in find_all(sym, "property"):
        if p[1].startswith("ki_"):
            continue
        p = copy.deepcopy(p)
        at = find(p, "at")
        at[1], at[2] = r2(x + float(at[1])), r2(y - float(at[2]))
        p[2] = Q({"Reference": ref, "Value": value,
                  "Footprint": footprint if footprint is not None else p[2],
                  "Datasheet": datasheet if datasheet is not None else p[2]}.get(p[1], p[2]))
        inst.append(p)
    pins = pins_of(sym)
    unknown = set(nets) - {p[0] for p in pins}
    assert not unknown, (ref, unknown)
    for num in dict.fromkeys(p[0] for p in pins):
        inst.append(["pin", Q(num), ["uuid", uid("pin", ref, num)]])
    inst.append(["instances", ["project", Q("tablo"),
                               ["path", Q("/" + ROOT), ["reference", Q(ref)], ["unit", 1]]]])
    items.append(inst)
    done = {}
    for num, px, py, ang, _kind in pins:
        sx, sy = r2(x + px), r2(y - py)
        net = nets.get(num)
        if (sx, sy) in done:
            assert net in (None, done[(sx, sy)]), (ref, num, net, done[(sx, sy)])
            continue
        if net is None:
            stacked = [n for (q, qx, qy, _, _) in pins if (r2(x + qx), r2(y - qy)) == (sx, sy)
                       for n in [nets.get(q)] if n]
            net = stacked[0] if stacked else None
        done[(sx, sy)] = net
        if net is None:
            assert nc_ok, (ref, num)
            items.append(["no_connect", ["at", sx, sy], ["uuid", uid("nc", ref, num)]])
            continue
        dx, dy = OUT[ang]
        ex, ey = sx + dx * STUB, sy + dy * STUB
        wire(sx, sy, ex, ey)
        label(net, ex, ey, (dx, dy))


# shorthands for two-pin parts -----------------------------------------------------

def R(ref, val, x, y, top, bot, fp="Resistor_SMD:R_0402_1005Metric"):
    place("Device:R", ref, val, x, y, {"1": top, "2": bot}, fp)


def C(ref, val, x, y, top, bot, fp="Capacitor_SMD:C_0402_1005Metric"):
    place("Device:C", ref, val, x, y, {"1": top, "2": bot}, fp)


def L(ref, val, x, y, top, bot, fp):
    place("Device:L", ref, val, x, y, {"1": top, "2": bot}, fp)


def flag(n, net, x, y):
    place("power:PWR_FLAG", f"#FLG{n:02d}", "PWR_FLAG", x, y, {"1": net})


C0402, C0603, C0805 = ("Capacitor_SMD:C_0402_1005Metric", "Capacitor_SMD:C_0603_1608Metric",
                       "Capacitor_SMD:C_0805_2012Metric")

# ---------------------------------------------------------------- the circuit

# USB-C input ----------------------------------------------------------------------
text("USB-C input", 20, 32)
place("Connector:USB_C_Receptacle_USB2.0_16P", "J1", "USB-C", 40, 70, {
    "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND",
    "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
    "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DN", "B7": "USB_DN",
}, "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12")
R("R1", "5.1k", 80, 55, "CC1", "GND")
R("R2", "5.1k", 90, 55, "CC2", "GND")
place("Power_Protection:USBLC6-2SC6", "U6", "USBLC6-2SC6", 90, 90, {
    "1": "USB_DP", "6": "USB_DP", "3": "USB_DN", "4": "USB_DN", "2": "GND", "5": "VBUS"})
flag(1, "VBUS", 58, 40)
flag(2, "GND", 66, 40)

# Charger -------------------------------------------------------------------------
text("Charger with power path", 115, 32)
note("ISET 1.0k: 0.9 A charge. ILIM 1.1k: 1.46 A input limit (EN2 high, EN1 low).\nOUT regulated to 4.4 V. TMR and ITERM open: default timers, 10% termination.\nTS on 10k: no battery thermistor.", 115, 112)
place("Battery_Management:BQ24074RGT", "U2", "BQ24074RGT", 160, 72, {
    "13": "VBUS", "10": "VSYS", "11": "VSYS", "2": "VBAT", "3": "VBAT",
    "1": "CHG_TS", "4": "GND", "5": "VSYS", "6": "GND", "7": "USB_PG_N", "9": "CHG_N",
    "12": "CHG_ILIM", "16": "CHG_ISET", "8": "GND", "17": "GND",
})
R("R3", "1.0k", 125, 100, "CHG_ISET", "GND")
R("R4", "1.1k", 133, 100, "CHG_ILIM", "GND")
R("R5", "10k", 190, 100, "CHG_TS", "GND")
C("C1", "10u", 125, 45, "VBUS", "GND", C0805)
C("C2", "10u", 195, 45, "VSYS", "GND", C0805)
C("C3", "10u", 203, 45, "VBAT", "GND", C0805)
R("R6", "100k", 200, 100, "+3V3", "USB_PG_N")
R("R7", "100k", 208, 100, "+3V3", "CHG_N")

# Battery and fuel gauge -------------------------------------------------------------
text("Battery and fuel gauge", 222, 32)
note("MAX17048: I2C address 0x36. ALRT wakes the board on low battery.", 222, 112)
place("Connector_Generic:Conn_01x02", "J2", "LiPo 604060", 245, 60, {"1": "VBAT", "2": "GND"},
      "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal")
place("tablo:MAX17048", "U3", "MAX17048G+T10", 270, 82, {
    "3": "VBAT", "2": "VBAT", "1": "GND", "6": "GND", "4": "GND", "9": "GND",
    "8": "I2C_SDA", "7": "I2C_SCL", "5": "BAT_ALRT_N"})
C("C4", "100n", 245, 95, "VBAT", "GND")
R("R8", "4.7k", 290, 60, "+3V3", "I2C_SDA")
R("R9", "4.7k", 298, 60, "+3V3", "I2C_SCL")
R("R10", "100k", 306, 60, "+3V3", "BAT_ALRT_N")

# 3.3 V buck-boost ---------------------------------------------------------------------
text("3.3 V buck-boost and power switch", 318, 32)
place("Switch:SW_SPDT", "SW11", "Power", 325, 55, {"1": "VSYS", "2": "REG_EN", "3": "GND"},
      "Button_Switch_SMD:SW_SPDT_PCM12")
place("tablo:TPS63802", "U4", "TPS63802DLAR", 355, 80, {
    "10": "VSYS", "1": "REG_EN", "2": "GND", "3": "GND", "8": "GND",
    "6": "+3V3", "4": "REG_FB", "9": "REG_L1", "7": "REG_L2"})
L("L1", "0.47u", 385, 55, "REG_L1", "REG_L2", "Inductor_SMD:L_Taiyo-Yuden_NR-40xx")
C("C5", "10u", 330, 100, "VSYS", "GND", C0805)
C("C6", "22u", 375, 100, "+3V3", "GND", C0805)
R("R11", "511k", 390, 100, "+3V3", "REG_FB")
R("R12", "91k", 398, 100, "REG_FB", "GND")
note("L1: 0.47 uH, e.g. Coilcraft XFL4015-471ME.\nFB 511k/91k: 3.3 V. MODE low: power save.\nSW11 off: the regulator stops, only the charger\nand the fuel gauge stay on the battery.", 318, 112)

# ESP32-S3 ------------------------------------------------------------------------------
text("ESP32-S3-WROOM-1U-N16R8", 105, 125)
place("RF_Module:ESP32-S3-WROOM-1", "U1", "ESP32-S3-WROOM-1U-N16R8", 165, 197, {
    "1": "GND", "40": "GND", "41": "GND", "2": "+3V3", "3": "EN", "27": "BOOT",
    # GPIO3 is a strapping pin, so button 3 goes to GPIO14 (still an RTC GPIO)
    "39": "BTN1", "38": "BTN2", "22": "BTN3", "4": "BTN4", "5": "BTN5", "6": "BTN6", "7": "BTN7",
    "12": "BTN8",
    "17": "I2C_SDA", "18": "I2C_SCL", "19": "USB_PG_N", "20": "CHG_N", "21": "BAT_ALRT_N",
    "8": "XTAL32_P", "9": "XTAL32_N", "13": "USB_DN", "14": "USB_DP",
    "31": "EPD_RST", "32": "EPD_DC", "33": "EPD_SCK", "34": "EPD_MOSI", "35": "EPD_CS",
    "24": "EPD_BUSY", "25": "EPD_PWR", "37": "UART_TX", "36": "UART_RX",
}, "RF_Module:ESP32-S3-WROOM-1U")
R("R13", "10k", 112, 140, "+3V3", "EN")
C("C7", "1u", 120, 140, "EN", "GND", C0603)
place("Switch:SW_Push", "SW9", "RESET", 135, 135, {"1": "EN", "2": "GND"},
      "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A")
place("Switch:SW_Push", "SW10", "BOOT", 135, 147, {"1": "BOOT", "2": "GND"},
      "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A")
C("C8", "22u", 195, 140, "+3V3", "GND", C0805)
C("C9", "100n", 203, 140, "+3V3", "GND")
place("Device:Crystal", "Y1", "32.768k", 125, 240, {"1": "XTAL32_P", "2": "XTAL32_N"},
      "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm")
C("C10", "12p", 105, 255, "XTAL32_P", "GND")
C("C11", "12p", 145, 255, "XTAL32_N", "GND")
note("C10, C11: set from the crystal's load capacitance.", 100, 270)
for i, (net, x) in enumerate([("+3V3", 165), ("GND", 175), ("VBAT", 185), ("VSYS", 195),
                              ("UART_TX", 210), ("UART_RX", 225)]):
    place("Connector:TestPoint", f"TP{i + 1}", net, x, 245, {"1": net},
          "TestPoint:TestPoint_Pad_D1.0mm")

# Buttons ------------------------------------------------------------------------------
text("Buttons: Kailh Choc v1, soldered", 20, 125)
for i in range(8):
    R(f"R{20 + i}", "100k", 22 + i * 9, 140, "+3V3", f"BTN{i + 1}")
    place("Switch:SW_Push", f"SW{i + 1}", f"Choc K{i + 1}", 50, 165 + i * 13,
          {"1": f"BTN{i + 1}", "2": "GND"}, "tablo:Kailh_Choc_V1")
note("Footprint tablo:Kailh_Choc_V1 is drawn with the layout.", 20, 275)

# Screen ----------------------------------------------------------------------------------
text("E-paper GDEY075T7: reference circuit (spec section 11)", 250, 125)
place("Connector_Generic:Conn_01x24", "J3", "GDEY075T7 FPC", 398, 142, {
    "2": "EPD_GDR", "3": "EPD_RESE", "5": "EPD_VSHR", "8": "GND", "9": "EPD_BUSY",
    "10": "EPD_RST", "11": "EPD_DC", "12": "EPD_CS", "13": "EPD_SCK", "14": "EPD_MOSI",
    "15": "EPD_3V3", "16": "EPD_3V3", "17": "GND", "18": "EPD_VDD", "20": "EPD_VSH1",
    "21": "EPD_PREVGH", "22": "EPD_VSL", "23": "EPD_PREVGL", "24": "EPD_VCOM",
}, "Connector_FFC-FPC:Hirose_FH12-24S-0.5SH_1x24-1MP_P0.50mm_Horizontal")
for i, net in enumerate(["EPD_VSHR", "EPD_VSH1", "EPD_VSL", "EPD_PREVGL"]):
    C(f"C{20 + i}", "4.7u 25V", 300 + i * 10, 215, net, "GND", C0805)
for i, net in enumerate(["EPD_3V3", "EPD_VDD", "EPD_VCOM"]):
    C(f"C{24 + i}", "1u 25V", 340 + i * 10, 215, net, "GND", C0603)
L("L2", "10u 1A", 258, 150, "EPD_3V3", "EPD_SW", "Inductor_SMD:L_Taiyo-Yuden_NR-40xx")
place("Transistor_FET:Si1308EDL", "Q1", "Si1308EDL", 280, 185,
      {"1": "EPD_GDR", "2": "EPD_RESE", "3": "EPD_SW"})
R("R14", "1M", 262, 195, "EPD_GDR", "GND")
R("R15", "0.47", 295, 195, "EPD_RESE", "GND", "Resistor_SMD:R_0603_1608Metric")
C("C27", "4.7u 25V", 275, 145, "EPD_SW", "EPD_CP", C0805)
place("Diode:MBR0530", "D1", "MBR0530", 300, 140, {"1": "EPD_CP", "2": "EPD_PREVGL"})
place("Diode:MBR0530", "D2", "MBR0530", 300, 152, {"1": "GND", "2": "EPD_CP"})
place("Diode:MBR0530", "D3", "MBR0530", 300, 164, {"1": "EPD_PREVGH", "2": "EPD_SW"})
C("C28", "4.7u 25V", 325, 160, "EPD_PREVGH", "GND", C0805)
C("C29", "4.7u 25V", 335, 160, "EPD_3V3", "GND", C0805)
place("Power_Management:TPS22917DBV", "U5", "TPS22917DBV", 290, 235, {
    "1": "+3V3", "3": "EPD_PWR", "2": "GND", "6": "EPD_3V3"})
R("R16", "100k", 262, 245, "EPD_PWR", "GND")
C("C30", "1u", 320, 235, "+3V3", "GND", C0603)

# ---------------------------------------------------------------- write files

sch = ["kicad_sch", ["version", VERSION], ["generator", Q("eeschema")], ["generator_version", Q("10.0")],
       ["uuid", ROOT], ["paper", Q("A3")],
       ["title_block", ["title", Q("Tablo T75 main board")], ["date", Q("2026-11-09")], ["rev", Q("0.1")],
        ["comment", 1, Q("Bootstrapped by pcb/tools/gen_schematic.py; nets are joined by labels")]],
       ["lib_symbols"] + list(used_libs.values())] + items + [
       ["sheet_instances", ["path", Q("/"), ["page", Q("1")]]], ["embedded_fonts", "no"]]

with open(os.path.join(PCB, "tablo.kicad_sch"), "w", encoding="utf-8") as f:
    f.write(dump(sch) + "\n")
with open(os.path.join(PCB, "tablo.kicad_sym"), "w", encoding="utf-8") as f:
    f.write(dump(["kicad_symbol_lib", ["version", VERSION], ["generator", Q("kicad_symbol_editor")],
                  ["generator_version", Q("10.0")]] + CUSTOM) + "\n")
print(f"{len(refs_seen)} symbols, {sum(1 for i in items if i[0] == 'label')} labels")
