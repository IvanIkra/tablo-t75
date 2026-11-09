"""Order package helpers for pcb/tablo.kicad_pcb (run with KiCad's Python, it needs pcbnew).

  bom   <board> <parts.csv> <out.csv>   BOM grouped by value and footprint, with the manufacturer
                                        part numbers from parts.csv; parts not fitted are listed apart
  pos   <board> <out.csv>               pick-and-place for the fitted parts on the top side,
                                        relative to the board's file origin (bottom-left corner), Y up
  panel <board> <out.kicad_pcb>         an assembly panel: the board with a rail along each long edge,
                                        joined by tabs with mouse bites, fiducials and tooling holes
                                        on the rails (assembly lines want boards of 70 x 70 mm or more)

export_fab.sh calls these; see pcb/README.md.
"""

import csv
import sys
from collections import OrderedDict

import pcbnew

MM = pcbnew.FromMM
FID_LIB = '/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Fiducial.pretty'

# panel geometry, mm
RAIL = 12.5          # rail width: 41.6 + 2 x (2 + 12.5) = 70.6 mm panel height
CHANNEL = 2.0        # milled gap between the board and a rail
TAB = 5.0            # tab length along the edge
BITE_D = 0.5         # mouse-bite hole diameter
BITE_PITCH = 0.8
TAB_CLEAR = 0.6      # copper must stay this far from the board edge along a tab
TOOLING_D = 2.0


def ref_key(ref):
    head = ref.rstrip('0123456789')
    tail = ref[len(head):]
    return head, int(tail) if tail else 0


def compress(refs):
    """C1,C2,C3,C5 -> C1-C3,C5"""
    runs = []
    for r in sorted(refs, key=ref_key):
        head, num = ref_key(r)
        if runs and runs[-1][-1][0] == head and runs[-1][-1][1] == num - 1:
            runs[-1].append((head, num))
        else:
            runs.append([(head, num)])
    out = []
    for run in runs:
        names = [f'{h}{n}' for h, n in run]
        out.append(f'{names[0]}-{names[-1]}' if len(names) > 2 else ','.join(names))
    return ','.join(out)


def parts_table(path):
    with open(path, newline='') as fh:
        return {(row['Value'], row['Footprint']): row for row in csv.DictReader(fh)}


def board_parts(board):
    for fp in board.GetFootprints():
        if fp.IsBoardOnly():
            continue
        yield fp


def bom(board_path, parts_path, out_path):
    board = pcbnew.LoadBoard(board_path)
    table = parts_table(parts_path)
    groups = OrderedDict()
    for fp in sorted(board_parts(board), key=lambda f: ref_key(f.GetReference())):
        key = (fp.GetValue(), str(fp.GetFPID().GetUniStringLibId()))
        groups.setdefault(key, []).append(fp)
    missing = [k for k in groups if k not in table]
    if missing:
        sys.exit('parts missing from %s: %s' % (parts_path, missing))
    fitted = [(k, v) for k, v in groups.items() if table[k]['Fit'] == 'yes']
    unfitted = [(k, v) for k, v in groups.items() if table[k]['Fit'] != 'yes']
    for k, fps in groups.items():
        if (table[k]['Fit'] == 'yes') == any(f.IsDNP() for f in fps):
            sys.exit(f'{k}: Fit in {parts_path} does not match the DNP flag on the board')
    with open(out_path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['Item', 'Designator', 'Qty', 'Value', 'Package', 'Manufacturer', 'MPN', 'Description', 'Notes', 'Fit'])
        item = 0
        # merge rows that share a part number (e.g. 1u and 1u 25V use the same capacitor)
        merged = OrderedDict()
        for k, fps in fitted:
            row = table[k]
            mk = (row['Manufacturer'], row['MPN'], k[1])
            merged.setdefault(mk, [row, []])[1].extend(fps)
        for (_, _, footprint), (row, fps) in merged.items():
            item += 1
            refs = [f.GetReference() for f in fps]
            values = sorted({f.GetValue() for f in fps})
            w.writerow([item, compress(refs), len(refs), ' / '.join(values), footprint.split(':')[1],
                        row['Manufacturer'], row['MPN'], row['Description'], row['Notes'], 'yes'])
        spare = OrderedDict()
        for k, fps in unfitted:
            row = table[k]
            spare.setdefault((row['Manufacturer'], row['MPN'], row['Description'], k[1]), [row, []])[1].extend(fps)
        for (_, _, _, footprint), (row, fps) in spare.items():
            item += 1
            refs = [f.GetReference() for f in fps]
            values = sorted({f.GetValue() for f in fps}, key=lambda v: v)
            w.writerow([item, compress(refs), len(refs), ' / '.join(values) if len(values) < 4 else '', footprint.split(':')[1],
                        row['Manufacturer'], row['MPN'], row['Description'], row['Notes'], 'DNP'])
    n_fit = sum(len(v[1]) for v in merged.values())
    print(f'BOM: {len(merged)} lines, {n_fit} parts to fit, {sum(len(v) for _, v in unfitted)} not fitted')


def pos(board_path, out_path):
    board = pcbnew.LoadBoard(board_path)
    origin = board.GetDesignSettings().GetAuxOrigin()
    rows = []
    for fp in board_parts(board):
        if fp.IsDNP() or fp.IsExcludedFromPosFiles() or fp.IsFlipped():
            continue
        p = fp.GetPosition()
        rows.append([fp.GetReference(), fp.GetValue(), fp.GetFPID().GetUniStringLibItemName(),
                     '%.3f' % pcbnew.ToMM(p.x - origin.x), '%.3f' % pcbnew.ToMM(origin.y - p.y),
                     '%.1f' % (fp.GetOrientationDegrees() % 360), 'top'])
    rows.sort(key=lambda r: ref_key(r[0]))
    with open(out_path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['Designator', 'Value', 'Package', 'Mid X', 'Mid Y', 'Rotation', 'Layer'])
        w.writerows(rows)
    print(f'pick-and-place: {len(rows)} parts, origin = board bottom-left corner')


def edge_rect(board):
    """The board outline rectangle (the largest closed shape on Edge.Cuts)."""
    pts = [p for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts for p in (d.GetStart(), d.GetEnd())]
    return (min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts))


def copper_near_edge(board, x, y, length):
    """True if any track, via or pad comes within TAB_CLEAR of the edge segment at y from x to x+length."""
    probe = pcbnew.SHAPE_SEGMENT(pcbnew.VECTOR2I(x, y), pcbnew.VECTOR2I(x + length, y), 1)
    clear = MM(TAB_CLEAR)
    for t in board.GetTracks():
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu):
            if t.IsOnLayer(layer) and t.GetEffectiveShape(layer).Collide(probe, clear):
                return True
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetEffectiveShape(pcbnew.F_Cu).Collide(probe, clear):
                return True
    return False


def tab_positions(board, x0, x1, y, count=3):
    """count tab positions spread along the edge where no copper is close to it."""
    span = x1 - x0
    tabs = []
    for i in range(count):
        want = x0 + span * (i + 0.5) / count - MM(TAB) / 2
        best = None
        for step in range(0, int(span / MM(0.5))):
            for sign in (1, -1):
                cand = want + sign * step * MM(0.5)
                if cand < x0 + MM(8) or cand + MM(TAB) > x1 - MM(8):
                    continue
                if not copper_near_edge(board, int(cand), y, MM(TAB)):
                    best = int(cand)
                    break
            if best is not None:
                break
        if best is None:
            sys.exit(f'no room for a tab near x = {pcbnew.ToMM(want):.1f} mm, y = {pcbnew.ToMM(y):.1f} mm')
        tabs.append(best)
    return tabs


def add_rect_outline(poly, x0, y0, x1, y1):
    poly.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        poly.Append(int(x), int(y))


def add_npth(board, name, x, y, d, mask=None):
    fp = pcbnew.FOOTPRINT(board)
    fp.SetReference(name)
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    fp.SetBoardOnly(True)
    fp.SetExcludedFromBOM(True)
    fp.SetExcludedFromPosFiles(True)
    fp.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
    pad = pcbnew.PAD(fp)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(pcbnew.VECTOR2I(MM(d), MM(d)))
    pad.SetDrillSize(pcbnew.VECTOR2I(MM(d), MM(d)))
    pad.SetLayerSet(pcbnew.LSET.AllCuMask().addLayer(pcbnew.F_Mask).addLayer(pcbnew.B_Mask))
    pad.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
    fp.Add(pad)
    board.Add(fp)


def panel(board_path, out_path):
    board = pcbnew.LoadBoard(board_path)
    x0, y0, x1, y1 = edge_rect(board)
    top_tabs = tab_positions(board, x0, x1, y0)
    bot_tabs = tab_positions(board, x0, x1, y1)

    # new outline: board + rails + tabs, as one polygon; the inner cut-outs (the FPC slot) stay
    outline = pcbnew.SHAPE_POLY_SET()
    add_rect_outline(outline, x0, y0, x1, y1)
    rails = pcbnew.SHAPE_POLY_SET()
    add_rect_outline(rails, x0, y0 - MM(CHANNEL + RAIL), x1, y0 - MM(CHANNEL))
    add_rect_outline(rails, x0, y1 + MM(CHANNEL), x1, y1 + MM(CHANNEL + RAIL))
    for tx in top_tabs:
        add_rect_outline(rails, tx, y0 - MM(CHANNEL) - 1, tx + MM(TAB), y0 + 1)
    for tx in bot_tabs:
        add_rect_outline(rails, tx, y1 - 1, tx + MM(TAB), y1 + MM(CHANNEL) + 1)
    outline.BooleanAdd(rails)
    outline.Simplify()

    outer = [d for d in board.GetDrawings()
             if d.GetLayer() == pcbnew.Edge_Cuts and _on_rect(d, x0, y0, x1, y1)]
    width = outer[0].GetWidth()
    for d in outer:
        board.Remove(d)
    # the outer outline, and the channels between the tabs (holes of the polygon)
    chains = [outline.Outline(0)] + [outline.Hole(0, h) for h in range(outline.HoleCount(0))]
    for chain in chains:
        for i in range(chain.PointCount()):
            a, b = chain.CPoint(i), chain.CPoint((i + 1) % chain.PointCount())
            seg = pcbnew.PCB_SHAPE(board)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetLayer(pcbnew.Edge_Cuts)
            seg.SetWidth(width)
            seg.SetStart(a)
            seg.SetEnd(b)
            board.Add(seg)

    # mouse bites along the board edge of every tab, centred on the edge
    n = 0
    for tabs, y in ((top_tabs, y0), (bot_tabs, y1)):
        for tx in tabs:
            count = int(MM(TAB) // MM(BITE_PITCH))
            start = tx + (MM(TAB) - (count - 1) * MM(BITE_PITCH)) // 2
            for k in range(count):
                n += 1
                add_npth(board, f'MB{n}', start + k * MM(BITE_PITCH), y, BITE_D)

    # fiducials and tooling holes on the rails
    rail_mid_top = y0 - MM(CHANNEL + RAIL / 2)
    rail_mid_bot = y1 + MM(CHANNEL + RAIL / 2)
    for i, (x, y) in enumerate(((x0 + MM(12), rail_mid_top), (x1 - MM(12), rail_mid_top),
                                (x0 + MM(12), rail_mid_bot)), 1):
        fid = pcbnew.FootprintLoad(FID_LIB, 'Fiducial_1mm_Mask2mm')
        fid.SetReference(f'PFID{i}')
        fid.Reference().SetVisible(False)
        fid.SetBoardOnly(True)
        fid.SetExcludedFromBOM(True)
        fid.SetExcludedFromPosFiles(True)
        fid.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
        board.Add(fid)
    for i, (x, y) in enumerate(((x0 + MM(5), rail_mid_top), (x1 - MM(5), rail_mid_top),
                                (x0 + MM(5), rail_mid_bot), (x1 - MM(5), rail_mid_bot)), 1):
        add_npth(board, f'TH{i}', x, y, TOOLING_D)

    # the file origin goes to the panel's bottom-left corner
    board.GetDesignSettings().SetAuxOrigin(pcbnew.VECTOR2I(x0, y1 + MM(CHANNEL + RAIL)))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.Save(out_path)
    size = (pcbnew.ToMM(x1 - x0), pcbnew.ToMM(y1 - y0) + 2 * (CHANNEL + RAIL))
    print('panel: %.1f x %.1f mm, tabs at x = %s (top), %s (bottom)' % (
        size[0], size[1], [round(pcbnew.ToMM(t), 1) for t in top_tabs], [round(pcbnew.ToMM(t), 1) for t in bot_tabs]))


def _on_rect(shape, x0, y0, x1, y1):
    """True for an Edge.Cuts segment lying on the outer board rectangle."""
    if shape.GetShape() != pcbnew.SHAPE_T_SEGMENT:
        return shape.GetShape() == pcbnew.SHAPE_T_RECTANGLE
    s, e = shape.GetStart(), shape.GetEnd()
    tol = MM(0.01)
    on_x = lambda x: abs(x - x0) < tol or abs(x - x1) < tol
    on_y = lambda y: abs(y - y0) < tol or abs(y - y1) < tol
    return (on_x(s.x) and on_x(e.x) and s.x == e.x) or (on_y(s.y) and on_y(e.y) and s.y == e.y)


if __name__ == '__main__':
    mode, *args = sys.argv[1:]
    {'bom': bom, 'pos': pos, 'panel': panel}.get(mode, lambda *a: sys.exit(__doc__))(*args)
