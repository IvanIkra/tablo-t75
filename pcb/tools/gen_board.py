"""Build pcb/tablo.kicad_pcb from the schematic netlist: outline, placement, zones.

Run with the Python that ships with KiCad (it has the pcbnew module):
  kicad-cli sch export netlist --format kicadsexpr -o tablo.net pcb/tablo.kicad_sch
  <KiCad python> pcb/tools/gen_board.py build tablo.net
  <KiCad python> pcb/tools/gen_board.py export geom.json
  uv run --no-project --with numpy --with scipy python pcb/tools/route.py geom.json routes.json
  <KiCad python> pcb/tools/gen_board.py apply routes.json

Board coordinates are the enclosure model's (cad/tablo.scad) seen from the back:
X = model x, Y = 146 - model y. The parts sit on F.Cu, which faces the back
cover; the Choc switches go in from B.Cu, which faces the switch plate.
Like gen_schematic.py, this only bootstraps the board.
"""

import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(__file__))
from sexpr import find, find_all, parse  # noqa: E402

PCB = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
FPDIR = os.environ.get("KICAD_FOOTPRINT_DIR",
                       "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")
H = 146.0


def mm(v):
    return pcbnew.FromMM(v)


def pt(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def model(x, y):
    """Enclosure model coordinates -> board coordinates."""
    return x, H - y


# ---------------------------------------------------------------- enclosure numbers (cad/tablo.scad)
W, ACT_W, N_KEYS, TOP_BEZEL, ACT_H, ACT_OFF_TOP, PAN_H = 185, 163.2, 8, 12, 97.92, 3.49, 111.2
PITCH = ACT_W / N_KEYS
PAN_Y0 = (H - TOP_BEZEL) + ACT_OFF_TOP - PAN_H          # 26.29
KEY_CY = PAN_Y0 - 3 - 15.4 / 2 - 0.5                    # 15.09
FPC_X = (W - 170.2) / 2 + 79.9                           # 87.3


def kx(i):
    return W / 2 - (i - (N_KEYS - 1) / 2) * PITCH


BOARD = (2.5, 8.7, 176.0, 50.3)                         # model x0, y0, x1, y1
SLOT = (FPC_X - 7.0, 23.5, FPC_X + 7.0, 25.5)            # the screen FPC goes through it

# ---------------------------------------------------------------- netlist


def read_netlist(path):
    tree = parse(open(path, encoding="utf-8").read())[0]
    comps = {}
    for c in find_all(find(tree, "components"), "comp"):
        desc = find(c, "description")
        ds = [f for f in find_all(find(c, "fields") or [], "field") if find(f, "name")[1] == "Datasheet"]
        comps[find(c, "ref")[1]] = (find(c, "value")[1], find(c, "footprint")[1], desc[1] if desc else "",
                                    ds[0][2] if ds and len(ds[0]) > 2 else "")
    nets = {}
    for n in find_all(find(tree, "nets"), "net"):
        name = find(n, "name")[1]
        for node in find_all(n, "node"):
            nets[(find(node, "ref")[1], find(node, "pin")[1])] = name
    return comps, nets


# ---------------------------------------------------------------- placement (model coords, rotation deg)
# None = leave for later; flip = mount on B.Cu
P = {}


def at(ref, x, y, rot=0, flip=False):
    P[ref] = (x, y, rot, flip)


for i in range(8):
    at(f"SW{i + 1}", kx(i), KEY_CY, 0, True)

# left end: USB-C at the wall, power switch below it
at("J1", 7.3, 36, 270)
at("SW11", 6.5, 19, 270)
at("U6", 17, 31, 0)
at("R1", 15.5, 41.5, 90)
at("R2", 15.5, 39.5, 90)
# charger: the parts sit next to the pins they belong to
at("U2", 26, 36, 0)
at("C1", 27.5, 41, 0)
at("R3", 24.2, 40.2, 90)
at("R4", 30.6, 37.6, 0)
at("R5", 21.4, 37.6, 0)
at("C3", 21.4, 34.6, 90)
at("C2", 30.8, 34.4, 90)
# 3.3 V regulator
at("U4", 41, 37, 0)
at("L1", 46.5, 41.5, 0)
at("C5", 36.5, 37, 90)
at("C6", 47.5, 35, 90)
at("R11", 44.5, 32, 0)
at("R12", 44.5, 30.5, 0)
# battery pads under the middle of the battery; the fuel gauge next to the module
at("J2", 101.6, 48.2, 0)
at("U3", 143, 33.5, 180)          # I2C and ALRT face the module
at("C4", 146.8, 33.5, 90)
at("R8", 136.2, 37.6, 270)
at("R9", 138.0, 37.6, 270)
at("R10", 139.8, 37.6, 270)
# screen power: booster and load switch
at("U5", 100.5, 31.5, 0)
at("C30", 103.6, 34.8, 90)
at("R16", 100.5, 28.2, 0)
at("L2", 72, 41, 0)
at("Q1", 72, 34.5, 0)
at("R14", 69, 34.5, 90)
at("R15", 75, 33, 90)
at("C27", 77, 38, 90)
at("D1", 77, 44.8, 0)
at("D2", 77, 41.5, 0)
at("D3", 74.5, 27.5, 0)
at("C28", 79.5, 37.5, 90)
at("C29", 69, 44.6, 0)
# screen FPC above the slot; its capacitors in a row along the top edge, clear of its pins
at("J3", FPC_X, 30.6, 0)
# in the order of their FPC pins (5, 15, 18, 20, 23, 24), so the rails do not cross;
# VSL (pin 22) gets its capacitor right of the connector, clear of PREVGL and PREVGH
for i, ref in enumerate(["C20", "C24", "C25", "C21", "C23", "C26"]):
    at(ref, 81 + i * 2.6, 45.6, 90)
at("C22", 97.6, 35.7, 90)
# module turned so its screen pins face the FPC; reset, boot and the crystal by their pins
at("U1", 116, 35.5, 180)
at("SW10", 101.5, 40.5, 0)
at("C8", 127.6, 30.2, 90)
at("C9", 129.4, 30.2, 90)
at("R13", 131.5, 26.8, 90)
at("C7", 133.2, 26.8, 90)
at("SW9", 138.5, 27.6, 0)
at("Y1", 128.2, 36.6, 90)
at("C10", 130.8, 38.6, 0)
at("C11", 130.8, 34.6, 0)
# pull-ups along the top edge, test pads below them
for i in range(8):
    at(f"R{20 + i}", 128 + i * 2.2, 45.2, 90)
at("R6", 145.6, 45.2, 90)
at("R7", 147.8, 45.2, 90)
for i in range(6):
    at(f"TP{i + 1}", 151 + i * 4.3, 37, 0)

# ---------------------------------------------------------------- net classes
POWER = ["/VBUS", "/VSYS", "/VBAT", "/REG_L1", "/REG_L2", "/EPD_3V3", "/EPD_SW"]


def build(netfile):
    comps, padnets = read_netlist(netfile)
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(4)
    ds.m_MinThroughDrill = mm(0.2)        # the module's thermal vias
    ds.m_ViasMinSize = mm(0.45)
    ds.m_MinClearance = mm(0.15)
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_CopperEdgeClearance = mm(0.3)

    netinfo = {}
    for name in sorted(set(padnets.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netinfo[name] = ni

    missing = set(comps) - set(P)
    assert not missing, f"no placement for {sorted(missing)}"
    for ref, (value, fpid, desc, datasheet) in sorted(comps.items()):
        lib, name = fpid.split(":")
        libpath = os.path.join(PCB, "tablo.pretty") if lib == "tablo" else os.path.join(FPDIR, lib + ".pretty")
        fp = pcbnew.FootprintLoad(libpath, name)
        assert fp is not None, fpid
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetField("Description", desc)
        fp.SetField("Datasheet", datasheet)
        fp.SetExcludedFromBOM(False)
        board.Add(fp)
        x, y, rot, flip = P[ref]
        fp.SetPosition(pt(*model(x, y)))
        if flip:
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            net = padnets.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(netinfo[net])
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
        fp.Reference().SetTextThickness(mm(0.12))

    # outline and the FPC slot
    x0, y0, x1, y1 = BOARD
    add_rect(board, *model(x0, y1), *model(x1, y0))
    sx0, sy0, sx1, sy1 = SLOT
    add_rect(board, *model(sx0, sy1), *model(sx1, sy0))

    # planes: GND on In1, +3V3 on In2, GND pour on both outer layers
    for layer, net, prio in [(pcbnew.In1_Cu, "/GND", 0), (pcbnew.In2_Cu, "/+3V3", 0),
                             (pcbnew.F_Cu, "/GND", 0), (pcbnew.B_Cu, "/GND", 0)]:
        add_zone(board, layer, netinfo[net], prio)
    return board


def add_rect(board, ax, ay, bx, by):
    for (p, q) in [((ax, ay), (bx, ay)), ((bx, ay), (bx, by)), ((bx, by), (ax, by)), ((ax, by), (ax, ay))]:
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pt(*p))
        seg.SetEnd(pt(*q))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(mm(0.1))
        board.Add(seg)


def add_zone(board, layer, net, prio):
    x0, y0, x1, y1 = BOARD
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(net)
    zone.SetAssignedPriority(prio)
    zone.SetLocalClearance(mm(0.2))
    zone.SetMinThickness(mm(0.15))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    outline = zone.Outline()
    outline.NewOutline()
    for x, y in [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]:
        X, Y = model(x, y)
        outline.Append(mm(X), mm(Y))
    board.Add(zone)


KEEPOUT_F = {"U1": 2.2}   # no tracks on F.Cu under the module, inside its pad ring


def export_geometry(board, path):
    """Pads, holes, outline and keep-outs for route.py."""
    import json
    x0, y0, x1, y1 = BOARD
    X0, Y1 = model(x0, y0)
    X1, Y0 = model(x1, y1)
    sx0, sy0, sx1, sy1 = SLOT
    SX0, SY1 = model(sx0, sy0)
    SX1, SY0 = model(sx1, sy1)
    geom = {"board": [X0, Y0, X1, Y1], "slots": [[SX0, SY0, SX1, SY1]], "holes": [], "pads": [],
            "keepout_F": [], "nets": {}}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref in KEEPOUT_F:
            bb = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
            k = KEEPOUT_F[ref]
            geom["keepout_F"].append([pcbnew.ToMM(bb.GetLeft()) + k, pcbnew.ToMM(bb.GetTop()) + k,
                                      pcbnew.ToMM(bb.GetRight()) - k, pcbnew.ToMM(bb.GetBottom()) - k])
        for pad in fp.Pads():
            pos = pad.GetPosition()
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                geom["holes"].append({"x": pcbnew.ToMM(pos.x), "y": pcbnew.ToMM(pos.y),
                                      "d": pcbnew.ToMM(pad.GetDrillSize().x)})
                continue
            layers = [name for name, lid in (("F.Cu", pcbnew.F_Cu), ("B.Cu", pcbnew.B_Cu)) if pad.IsOnLayer(lid)]
            poly = pad.GetEffectivePolygon(pcbnew.F_Cu if "F.Cu" in layers else pcbnew.B_Cu, pcbnew.ERROR_INSIDE)
            ol = poly.Outline(0)
            pts = [[pcbnew.ToMM(ol.CPoint(i).x), pcbnew.ToMM(ol.CPoint(i).y)] for i in range(ol.PointCount())]
            geom["pads"].append({"ref": ref, "num": pad.GetNumber(), "net": pad.GetNetname(), "layers": layers,
                                 "poly": pts, "center": [pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)],
                                 "pth": pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH,
                                 "drill": pcbnew.ToMM(pad.GetDrillSize().x)
                                 if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else 0})
    for name in {p["net"] for p in geom["pads"] if p["net"]}:
        geom["nets"][name] = board.FindNet(name).GetNetClassName()
    json.dump(geom, open(path, "w"))
    print("exported", len(geom["pads"]), "pads,", len(geom["holes"]), "holes")


def apply_routes(board, path):
    """Replace the tracks and vias with route.py's result, then fill the zones."""
    import json
    routes = json.load(open(path))
    for t in list(board.GetTracks()):
        board.Remove(t)
    for t in routes["tracks"]:
        layer = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In2.Cu": pcbnew.In2_Cu}[t["layer"]]
        net = board.FindNet(t["net"])
        for a, b in zip(t["pts"], t["pts"][1:]):
            if a == b:
                continue
            tr = pcbnew.PCB_TRACK(board)
            tr.SetStart(pt(*a))
            tr.SetEnd(pt(*b))
            tr.SetWidth(mm(t["w"]))
            tr.SetLayer(layer)
            tr.SetNet(net)
            board.Add(tr)
    for v in routes["vias"]:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pt(v["x"], v["y"]))
        via.SetWidth(mm(0.6))
        via.SetDrill(mm(0.3))
        via.SetNet(board.FindNet(v["net"]))
        board.Add(via)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print("applied", len(routes["tracks"]), "tracks,", len(routes["vias"]), "vias; failed:", len(routes["failed"]))


if __name__ == "__main__":
    out = os.path.join(PCB, "tablo.kicad_pcb")
    mode = sys.argv[1]
    if mode == "build":
        board = build(sys.argv[2])
        board.Save(out)
        print("saved", out, "footprints:", len(board.GetFootprints()))
    elif mode == "export":
        export_geometry(pcbnew.LoadBoard(out), sys.argv[2])
    elif mode == "apply":
        board = pcbnew.LoadBoard(out)
        apply_routes(board, sys.argv[2])
        board.Save(out)
