"""Hand a part of the layout to Freerouting and bring the result back.

Run with KiCad's Python (it needs the pcbnew module):

  export <board> <out.dsn> NET...   keep the board's tracks except those of NET...,
                                    drop the outer GND pours, make In1/In2 plane layers
                                    (so Freerouting routes only on F.Cu and B.Cu), write Specctra DSN
  import <board> <in.ses> <out>     replace the board's tracks with the session, fill the zones
  widen <board> <out>               widen Power-class segments that Freerouting necked down
                                    to 0.4 mm (or 0.35 mm) wherever the clearance allows

Freerouting itself (Java 25+, freerouting-2.5.0.jar from its GitHub release):

  java -Djava.awt.headless=true -jar freerouting-2.5.0.jar -de board.dsn -do board.ses \
      --router.autorouter.max_passes=200 -mt 1 --router.copper_to_edge_clearance_um=300 \
      --gui.enabled=false --api_server.enabled=false \
      --usage_and_diagnostic_data.disable_analytics=true

The FPC slot comes out of the DSN export as a keepout of its exact size, and Freerouting keeps only
the track clearance from it; grow that keepout by 0.15 mm in the .dsn first so that the 0.3 mm edge
rule holds (`export` does that).
"""

import re
import sys

import pcbnew

VIA = (0.6, 0.3)
SLOT_GROW_UM = 150
CLEAR = 0.15


def export(src, out, nets):
    board = pcbnew.LoadBoard(src)
    outer = [z for z in (board.GetArea(i) for i in range(board.GetAreaCount()))
             if not (z.GetIsRuleArea() or z.IsOnLayer(pcbnew.In1_Cu) or z.IsOnLayer(pcbnew.In2_Cu))]
    for zone in outer:
        board.Remove(zone)
    gone = [t for t in board.GetTracks() if t.GetNetname() in nets]
    for track in gone:
        board.Remove(track)
    print(f"removed {len(gone)} tracks and vias of {len(nets)} nets")
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_POWER)
    ns = board.GetDesignSettings().m_NetSettings
    for nc in [ns.GetDefaultNetclass()] + list(ns.GetNetclasses().values()):
        nc.SetViaDiameter(pcbnew.FromMM(VIA[0]))
        nc.SetViaDrill(pcbnew.FromMM(VIA[1]))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    if not pcbnew.ExportSpecctraDSN(board, out):
        sys.exit("DSN export failed")
    grow_keepouts(out)


def grow_keepouts(path):
    """Grow every rectangular keepout polygon in the DSN by SLOT_GROW_UM on each side."""
    text = open(path).read()

    def grow(m):
        nums = [int(v) for v in m.group(2).split()]
        xs, ys = nums[0::2], nums[1::2]
        x0, x1 = min(xs) - SLOT_GROW_UM, max(xs) + SLOT_GROW_UM
        y0, y1 = min(ys) - SLOT_GROW_UM, max(ys) + SLOT_GROW_UM
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        return m.group(1) + "  ".join(f"{x} {y}" for x, y in pts) + ")"

    text = re.sub(r'(\(keepout "" \(polygon signal 0\s+)([-\d\s]+)\)', grow, text)
    open(path, "w").write(text)


def import_ses(src, ses, out):
    board = pcbnew.LoadBoard(src)
    for track in list(board.GetTracks()):
        board.Remove(track)
    if not pcbnew.ImportSpecctraSES(board, ses):
        sys.exit("SES import failed")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(out)


def widen(src, out):
    board = pcbnew.LoadBoard(src)
    items = list(board.GetTracks())
    pads = [p for f in board.GetFootprints() for p in f.Pads()]
    narrow = [t for t in items if t.GetClass() == "PCB_TRACK" and t.GetNetClassName() == "Power"
              and t.GetWidth() < pcbnew.FromMM(0.4)]
    narrow.sort(key=lambda t: -t.GetLength())
    clear = pcbnew.FromMM(CLEAR)

    def fits(seg):
        layer = seg.GetLayer()
        shape = seg.GetEffectiveShape(layer)
        for other in items + pads:
            if other is seg or other.GetNetCode() == seg.GetNetCode() or not other.IsOnLayer(layer):
                continue
            if shape.Collide(other.GetEffectiveShape(layer), clear):
                return False
        return True

    done = 0
    for seg in narrow:
        old = seg.GetWidth()
        for width in (0.4, 0.35):
            seg.SetWidth(pcbnew.FromMM(width))
            if fits(seg):
                done += 1
                break
        else:
            seg.SetWidth(old)
    print(f"widened {done} of {len(narrow)} power segments")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(out)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    if mode == "export":
        export(args[0], args[1], set(args[2:]))
    elif mode == "import":
        import_ses(*args)
    elif mode == "widen":
        widen(*args)
    else:
        sys.exit(__doc__)
