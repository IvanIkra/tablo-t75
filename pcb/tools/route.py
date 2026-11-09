"""Grid router for the Tablo board.

Reads the geometry that gen_board.py exports, routes every net on F.Cu and
B.Cu (In2.Cu when it must) with A* on a 0.05 mm grid, drops GND and +3V3 pads onto the inner planes
with short stubs and vias, and writes the tracks and vias for gen_board.py to
apply. Clearances come from distance maps, so several track widths share one
set of maps per net.

Run:  uv run --no-project --with numpy --with scipy python pcb/tools/route.py geom.json routes.json [order]
order: "short" (default) routes signal nets from the shortest, "long" from the longest.
"""

import heapq
import json
import math
import sys

import numpy as np
from scipy import ndimage

RES = 0.05
MARGIN = 0.06             # copper drawn from cell centres can reach this far past them, plus rounding
EDGE_CLEAR = 0.3
HOLE_CLEAR = 0.25
VIA_D, VIA_DRILL = 0.6, 0.3
VIA_COST = 40.0            # in cells: a via costs as much as 2 mm of track
PLANES = {"/GND": "In1.Cu", "/+3V3": "In2.Cu"}
POWER_WIDTHS = [0.4, 0.3, 0.2]
PLANE_WIDTHS = [0.3, 0.2]
SIGNAL_WIDTHS = [0.2]
CLEAR = {"Power": 0.15, "Default": 0.15}
COPPER_HOLE_CLEAR = 0.2
MAX_EXPAND = 2_500_000
BIG_PAD = 1.5             # mm^2: pads at least this big may take vias (thermal pads)
STUB_MAX = 3.0            # mm: longest stub from a pad to its plane via
LAYERS = ["F.Cu", "B.Cu", "In2.Cu"]   # In2 carries the 3.3 V plane; tracks there cost more
LAYER_COST = [1.0, 1.0, 2.5]
# preferred directions: F.Cu and In2.Cu run along the board, B.Cu across it
DIR_COST = [(1.0, 2.0, 1.4), (2.0, 1.0, 1.4), (1.0, 2.0, 1.4)]   # (horizontal, vertical, diagonal)
TURN_COST = 3.0
EXIT_LEN = 1.2             # mm in front of each pad kept for its own net
EXIT_LEN_REF = {"J3": 3.0}  # the FPC connector fans out 24 pins at 0.5 mm
EXIT_COST = 6.0            # extra cost per cell for other nets crossing a pad's exit
NL = len(LAYERS)
S2 = math.sqrt(2)
DIRS = [(0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0), (1, 1, S2), (1, -1, S2), (-1, 1, S2), (-1, -1, S2)]


class SMask:
    """A boolean mask stored as a bounding-box slice of the grid."""

    def __init__(self, r0, c0, sub):
        self.r0, self.c0, self.sub = r0, c0, sub
        self.r1, self.c1 = r0 + sub.shape[0], c0 + sub.shape[1]

    def contains(self, r, c):
        return self.r0 <= r < self.r1 and self.c0 <= c < self.c1 and bool(self.sub[r - self.r0, c - self.c0])

    def paint(self, arr, value):
        view = arr[self.r0:self.r1, self.c0:self.c1]
        view[self.sub] = value

    def orin(self, arr):
        arr[self.r0:self.r1, self.c0:self.c1] |= self.sub

    def cells(self):
        rs, cs = np.nonzero(self.sub)
        return rs + self.r0, cs + self.c0

    def area(self):
        return int(self.sub.sum()) * RES * RES


class Grid:
    def __init__(self, geom):
        bx0, by0, bx1, by1 = geom["board"]
        self.x0, self.y0 = bx0, by0
        self.nx = int(math.ceil((bx1 - bx0) / RES)) + 1
        self.ny = int(math.ceil((by1 - by0) / RES)) + 1
        ys, xs = np.mgrid[0:self.ny, 0:self.nx]
        self.X = self.x0 + xs * RES
        self.Y = self.y0 + ys * RES
        hard = (self.X <= bx0) | (self.X >= bx1) | (self.Y <= by0) | (self.Y >= by1)
        for sx0, sy0, sx1, sy1 in geom["slots"]:
            hard |= (self.X >= sx0) & (self.X <= sx1) & (self.Y >= sy0) & (self.Y <= sy1)
        self.dist_edge = ndimage.distance_transform_edt(~hard) * RES
        self.drill = np.zeros((self.ny, self.nx), bool)     # every drilled hole, any net
        for h in geom["holes"]:
            self.drill |= self.disk(h["x"], h["y"], h["d"] / 2)
        self.npth = self.drill.copy()
        for p in geom["pads"]:
            if p.get("drill"):
                self.drill |= self.disk(p["center"][0], p["center"][1], p["drill"] / 2)
        self.dist_npth = ndimage.distance_transform_edt(~self.npth) * RES
        self.owner = np.zeros((NL, self.ny, self.nx), np.int32)
        for li in range(NL):
            self.owner[li][self.npth] = -1
        self.keepout = np.zeros((self.ny, self.nx), bool)
        for kx0, ky0, kx1, ky1 in geom["keepout_F"]:
            self.keepout |= (self.X >= kx0) & (self.X <= kx1) & (self.Y >= ky0) & (self.Y <= ky1)

    def rc(self, x, y):
        return int(round((y - self.y0) / RES)), int(round((x - self.x0) / RES))

    def xy(self, r, c):
        return round(self.x0 + c * RES, 4), round(self.y0 + r * RES, 4)

    def window(self, xmin, ymin, xmax, ymax):
        r0, c0 = self.rc(xmin, ymin)
        r1, c1 = self.rc(xmax, ymax)
        r0, c0 = max(r0 - 1, 0), max(c0 - 1, 0)
        r1, c1 = min(r1 + 2, self.ny), min(c1 + 2, self.nx)
        return r0, c0, r1, c1

    def disk(self, x, y, rad):
        r0, c0, r1, c1 = self.window(x - rad, y - rad, x + rad, y + rad)
        m = np.zeros((self.ny, self.nx), bool)
        m[r0:r1, c0:c1] = (self.X[r0:r1, c0:c1] - x) ** 2 + (self.Y[r0:r1, c0:c1] - y) ** 2 <= rad * rad
        return m

    def poly(self, pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        r0, c0, r1, c1 = self.window(min(xs), min(ys), max(xs), max(ys))
        X = self.X[r0:r1, c0:c1]
        Y = self.Y[r0:r1, c0:c1]
        inside = np.zeros(X.shape, bool)
        n = len(pts)
        for i in range(n):
            xa, ya = pts[i]
            xb, yb = pts[(i + 1) % n]
            if ya == yb:
                continue
            cond = (ya > Y) != (yb > Y)
            xint = xa + (Y - ya) * (xb - xa) / (yb - ya)
            inside ^= cond & (X < xint)
        if not inside.any():
            r, c = self.rc(sum(xs) / n, sum(ys) / n)
            inside[r - r0, c - c0] = True
        return SMask(r0, c0, inside)

    def segment(self, a, b, rad):
        (xa, ya), (xb, yb) = a, b
        r0, c0, r1, c1 = self.window(min(xa, xb) - rad, min(ya, yb) - rad, max(xa, xb) + rad, max(ya, yb) + rad)
        X = self.X[r0:r1, c0:c1]
        Y = self.Y[r0:r1, c0:c1]
        dx, dy = xb - xa, yb - ya
        L2 = dx * dx + dy * dy
        t = np.clip(((X - xa) * dx + (Y - ya) * dy) / L2, 0, 1) if L2 > 0 else np.zeros(X.shape)
        return SMask(r0, c0, (X - xa - t * dx) ** 2 + (Y - ya - t * dy) ** 2 <= rad * rad)


class Router:
    def __init__(self, geom):
        self.g = g = Grid(geom)
        self.geom = geom
        self.cls = geom["nets"]
        self.pads = geom["pads"]
        self.tracks, self.vias, self.failed = [], [], []
        self.ids = {}
        self.power_ids = set()
        for k, p in enumerate(self.pads):
            key = p["net"] or f"__nc_{k}"
            if key not in self.ids:
                self.ids[key] = len(self.ids) + 1
                if self.cls.get(p["net"]) == "Power":
                    self.power_ids.add(self.ids[key])
            p["id"] = self.ids[key]
            p["mask"] = g.poly(p["poly"])
            xs = [q[0] for q in p["poly"]]
            ys = [q[1] for q in p["poly"]]
            p["min_dim"] = min(max(xs) - min(xs), max(ys) - min(ys))
            if p["pth"]:
                p["layers"] = list(LAYERS)
            for li, layer in enumerate(LAYERS):
                if layer in p["layers"]:
                    p["mask"].paint(g.owner[li], p["id"])
        self.exits = self.pad_exits()
        self.pad_owner = g.owner.copy()      # copper that belongs to pads, never ripped up
        # under the module only GND may run (its thermal pad is GND anyway)
        g.owner[0][g.keepout & (g.owner[0] == 0)] = self.ids["/GND"]
        self.geo = {}              # net -> {"segs": [(li, a, b)], "vias": [(x, y)]} with exact coordinates
        self.power_lut = np.zeros(len(self.ids) + 2, bool)
        for i in self.power_ids:
            self.power_lut[i] = True
        self.plane_copper = {}     # plane net -> (NL, ny, nx) cells already tied to the plane
        self.retry = []            # connections that failed on the first pass
        self.trees = {}            # net -> (tree cells, pads joined to it)

    def pad_exits(self):
        """Per layer: which net owns the strip in front of each SMD pad (0 = nobody)."""
        g = self.g
        ex = np.zeros((NL, g.ny, g.nx), np.int32)
        cent = {}
        for p in self.pads:
            cent.setdefault(p["ref"], []).append(p["center"])
        for p in self.pads:
            if p["pth"] or not p["net"]:
                continue
            cx = sum(c[0] for c in cent[p["ref"]]) / len(cent[p["ref"]])
            cy = sum(c[1] for c in cent[p["ref"]]) / len(cent[p["ref"]])
            xs = [q[0] for q in p["poly"]]
            ys = [q[1] for q in p["poly"]]
            x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
            ln = EXIT_LEN_REF.get(p["ref"], EXIT_LEN)
            if (x1 - x0) >= (y1 - y0):
                if p["center"][0] >= cx:
                    box = (x1, y0 - 0.1, x1 + ln, y1 + 0.1)
                else:
                    box = (x0 - ln, y0 - 0.1, x0, y1 + 0.1)
            else:
                if p["center"][1] >= cy:
                    box = (x0 - 0.1, y1, x1 + 0.1, y1 + ln)
                else:
                    box = (x0 - 0.1, y0 - ln, x1 + 0.1, y0)
            r0, c0, r1, c1 = g.window(*box)
            sub = ((g.X[r0:r1, c0:c1] >= box[0]) & (g.X[r0:r1, c0:c1] <= box[2])
                   & (g.Y[r0:r1, c0:c1] >= box[1]) & (g.Y[r0:r1, c0:c1] <= box[3]))
            for li in self.pad_layers(p):
                view = ex[li, r0:r1, c0:c1]
                view[sub & (view == 0)] = p["id"]
        return ex

    # -- maps -----------------------------------------------------------------------------
    def net_maps(self, nid):
        """Distances from every cell to other nets' copper, split by their clearance class."""
        g = self.g
        out = []
        for li in range(NL):
            own = g.owner[li]
            other = (own != 0) & (own != nid)
            power = other & self.power_lut[np.clip(own, 0, None)]
            out.append((ndimage.distance_transform_edt(~(other & ~power)) * RES,
                        ndimage.distance_transform_edt(~power) * RES))
        return out

    def free(self, maps, width, clear):
        g = self.g
        res = []
        for d_sig, d_pow in maps:
            res.append((d_sig > width / 2 + clear + MARGIN)
                       & (d_pow > width / 2 + max(clear, CLEAR["Power"]) + MARGIN)
                       & (g.dist_edge > width / 2 + EDGE_CLEAR + MARGIN)
                       & (g.dist_npth > width / 2 + COPPER_HOLE_CLEAR + MARGIN))
        return res

    def via_ok(self, maps, nid, clear):
        g = self.g
        ok = self.free(maps, VIA_D, clear)
        small_own = np.zeros((g.ny, g.nx), bool)
        for p in self.pads:
            if p["id"] == nid and p["mask"].area() < BIG_PAD:
                p["mask"].orin(small_own)
        d_own = ndimage.distance_transform_edt(~small_own) * RES
        d_drill = ndimage.distance_transform_edt(~g.drill) * RES
        return (np.logical_and.reduce(ok) & (d_own > VIA_D / 2 + 0.1)
                & (d_drill > VIA_DRILL / 2 + HOLE_CLEAR + MARGIN))

    # -- A* -------------------------------------------------------------------------------
    def astar(self, starts, targets, free, viaok, nid=None):
        g = self.g
        nx, ny = g.nx, g.ny
        plane = nx * ny
        tmask = np.logical_or.reduce(targets)
        if not tmask.any() or not starts.any():
            return None
        h = ndimage.distance_transform_edt(~tmask).ravel()
        fb = [(free[li] | starts[li] | targets[li]).ravel().tobytes() for li in range(NL)]
        tb = [targets[li].ravel().tobytes() for li in range(NL)]
        vb = viaok.ravel().tobytes() if viaok is not None else bytes(plane)
        if nid is not None:
            pen = [((self.exits[li] != 0) & (self.exits[li] != nid)).ravel().tobytes() for li in range(NL)]
        else:
            pen = [bytes(plane)] * NL
        gscore, came, heap, closed = {}, {}, [], set()
        for li in range(NL):
            for idx in np.flatnonzero(starts[li].ravel()):
                s = li * plane + int(idx)
                gscore[s] = 0.0
                heapq.heappush(heap, (h[idx] * 1.001, 0.0, s))
        expanded = 0
        while heap:
            _, gc, s = heapq.heappop(heap)
            if s in closed:
                continue
            closed.add(s)
            li, idx = divmod(s, plane)
            if tb[li][idx]:
                path = [s]
                while s in came:
                    s = came[s]
                    path.append(s)
                return path[::-1]
            expanded += 1
            if expanded > MAX_EXPAND:
                return None
            r, c = divmod(idx, nx)
            f = fb[li]
            pl = pen[li]
            lc = LAYER_COST[li]
            hc, vc, dgc = DIR_COST[li]
            prev = came.get(s)
            if prev is not None and prev // plane == li:
                pr, pc = divmod(prev % plane, nx)
                pdir = (r - pr, c - pc)
            else:
                pdir = None
            for dr, dc, cost in DIRS:
                rr, cc = r + dr, c + dc
                if rr < 0 or cc < 0 or rr >= ny or cc >= nx:
                    continue
                j = rr * nx + cc
                if not f[j]:
                    continue
                if dr and dc and not (f[r * nx + cc] and f[rr * nx + c]):
                    continue
                t = li * plane + j
                ng = gc + cost * lc * (hc if dr == 0 else vc if dc == 0 else dgc)
                if pdir is not None and pdir != (dr, dc):
                    ng += TURN_COST
                if pl[j]:
                    ng += EXIT_COST
                if ng < gscore.get(t, 1e18):
                    gscore[t] = ng
                    came[t] = s
                    heapq.heappush(heap, (ng + h[j] * 1.001, ng, t))
            if vb[idx]:
                for lj in range(NL):
                    if lj == li or not fb[lj][idx]:
                        continue
                    t = lj * plane + idx
                    ng = gc + VIA_COST
                    if ng < gscore.get(t, 1e18):
                        gscore[t] = ng
                        came[t] = s
                        heapq.heappush(heap, (ng + h[idx] * 1.001, ng, t))
        return None

    # -- path geometry ---------------------------------------------------------------------
    def runs(self, path, ok):
        g = self.g
        plane = g.nx * g.ny
        cells = [(s // plane, *divmod(s % plane, g.nx)) for s in path]
        runs, cur = [], [cells[0]]
        for prev, cell in zip(cells, cells[1:]):
            if cell[0] != prev[0]:
                runs.append(cur)
                cur = [cell]
            else:
                cur.append(cell)
        runs.append(cur)
        out = []
        for run in runs:
            li = run[0][0]
            pts = self.smooth([(r, c) for _, r, c in run], ok[li])
            out.append([li, [g.xy(r, c) for r, c in pts]])
        vias = [g.xy(run[-1][1], run[-1][2]) for run in runs[:-1]]
        return out, vias

    def smooth(self, pts, ok):
        """Greedy string pulling restricted to 0/45/90 degree segments."""
        if len(pts) <= 2:
            return pts
        out, i = [pts[0]], 0
        while i < len(pts) - 1:
            best = i + 1
            for j in range(min(len(pts) - 1, i + 400), i + 1, -1):
                dr, dc = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
                if (dr == 0 or dc == 0 or abs(dr) == abs(dc)) and self.los(pts[i], pts[j], ok):
                    best = j
                    break
            out.append(pts[best])
            i = best
        return out

    @staticmethod
    def los(a, b, ok):
        n = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
        sr = (b[0] > a[0]) - (b[0] < a[0])
        sc = (b[1] > a[1]) - (b[1] < a[1])
        for k in range(n + 1):
            if not ok[a[0] + sr * k, a[1] + sc * k]:
                return False
        return True

    def commit(self, net, nid, runs, vias, width, tree):
        g = self.g
        for li, xy in runs:
            xy = [p for k, p in enumerate(xy) if k == 0 or p != xy[k - 1]]
            for a, b in zip(xy, xy[1:]):
                g.segment(a, b, width / 2).paint(g.owner[li], nid)
                if tree is not None:
                    g.segment(a, b, RES * 0.6).orin(tree[li])
            if len(xy) >= 2:
                self.tracks.append({"net": net, "layer": LAYERS[li], "w": width, "pts": [list(p) for p in xy]})
                self.geo.setdefault(net, {"segs": [], "vias": []})["segs"] += [(li, a, b) for a, b in zip(xy, xy[1:])]
        for x, y in vias:
            m = g.disk(x, y, VIA_D / 2)
            for li in range(NL):
                g.owner[li][m] = nid
                if tree is not None:
                    tree[li] |= m
                if net in self.plane_copper:
                    self.plane_copper[net][li] |= m
            g.drill |= g.disk(x, y, VIA_DRILL / 2)
            self.geo.setdefault(net, {"segs": [], "vias": []})["vias"].append((x, y))
            self.vias.append({"net": net, "x": x, "y": y})

    # -- connections --------------------------------------------------------------------------
    def pad_layers(self, p):
        return [LAYERS.index(layer) for layer in p["layers"] if layer in LAYERS]

    def pad_cells(self, p, free, width):
        """Free cells of a pad on its layers; the centre cell if none is free."""
        g = self.g
        m = np.zeros((NL, g.ny, g.nx), bool)
        for li in self.pad_layers(p):
            p["mask"].orin(m[li])
            m[li] &= free[li]
        if not m.any():
            if width > p["min_dim"] + 1e-6:
                return None              # too wide to leave this pad: try a narrower track
            r, c = g.rc(*p["center"])
            for li in self.pad_layers(p):
                m[li][r, c] = True
        return m

    def widths(self, net):
        if net in PLANES:
            return PLANE_WIDTHS
        return POWER_WIDTHS if self.cls.get(net) == "Power" else SIGNAL_WIDTHS

    def clear(self, net):
        return CLEAR.get(self.cls.get(net), CLEAR["Default"])

    def connect(self, net, nid, pad, tree, tree_pads, maps):
        g = self.g
        viaok = self.via_ok(maps, nid, self.clear(net))
        for width in self.widths(net):
            free = self.free(maps, width, self.clear(net))
            starts = self.pad_cells(pad, free, width)
            if starts is None:
                continue
            targets = tree & np.stack(free)
            for q in tree_pads:
                qc = self.pad_cells(q, free, width)
                if qc is not None:
                    targets |= qc
            path = self.astar(starts, targets, free, viaok, nid)
            if path is None:
                continue
            ok = [free[li] | starts[li] | targets[li] for li in range(NL)]
            runs, vias = self.runs(path, ok)
            if width <= pad["min_dim"] + 1e-6:
                runs[0][1].insert(0, tuple(pad["center"]))
            plane = g.nx * g.ny
            r, c = divmod(path[-1] % plane, g.nx)
            for q in tree_pads:
                if q["mask"].contains(r, c):
                    if width <= q["min_dim"] + 1e-6:
                        runs[-1][1].append(tuple(q["center"]))
                    break
            else:
                self.anchor_end(net, runs[-1])
            self.commit(net, nid, runs, vias, width, tree)
            return True
        return False

    def anchor_end(self, net, run):
        """End a track exactly on a via centre or on the centreline of a track of its net."""
        li, xy = run
        end = xy[-1]
        geo = self.geo.get(net, {"segs": [], "vias": []})
        best = None
        for v in geo["vias"]:
            d = math.dist(v, end)
            if d <= VIA_D / 2 + 1e-6 and (best is None or d < best[0]):
                best = (d, tuple(v))
        for lj, a, b in geo["segs"]:
            if lj != li:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((end[0] - a[0]) * dx + (end[1] - a[1]) * dy) / L2))
            q = (round(a[0] + t * dx, 4), round(a[1] + t * dy, 4))
            d = math.dist(q, end)
            if d <= 0.2 and (best is None or d < best[0]):
                best = (d, q)
        if best is not None and best[1] != tuple(end):
            xy.append(best[1])

    def route_net(self, net):
        pads = [p for p in self.pads if p["net"] == net]
        if len(pads) < 2:
            return
        g = self.g
        nid = pads[0]["id"]
        maps = self.net_maps(nid)
        tree = np.zeros((NL, g.ny, g.nx), bool)
        first = max(pads, key=lambda p: sum(1 for q in self.pads if q["ref"] == p["ref"]))
        done, todo = [first], [p for p in pads if p is not first]
        self.trees[net] = (tree, done)      # done: pads joined to the first one, never an island
        while todo:
            p = min(todo, key=lambda q: min(math.dist(q["center"], d["center"]) for d in done))
            todo.remove(p)
            touching = any(d["ref"] == p["ref"] and self.touch(d, p) for d in done)
            if touching or self.connect(net, nid, p, tree, done, maps):
                done.append(p)
            else:
                self.retry.append((net, nid, p))

    @staticmethod
    def touch(a, b):
        rs, cs = b["mask"].cells()
        return any(a["mask"].contains(r, c) for r, c in zip(rs, cs))

    def plane_stub(self, net, pad, maps, record=True):
        """Tie an SMD pad to the inner plane: a via near it, or existing plane copper."""
        g = self.g
        nid = pad["id"]
        tied = self.plane_copper[net]
        viaok = self.via_ok(maps, nid, self.clear(net))
        li = self.pad_layers(pad)[0]
        for width in self.widths(net):
            free = self.free(maps, width, self.clear(net))
            starts = self.pad_cells(pad, free, width)
            if starts is None:
                continue
            if (starts & tied).any():
                return True
            targets = np.zeros((NL, g.ny, g.nx), bool)
            targets[li] = (viaok & free[li]) | (tied[li] & free[li])
            path = self.astar(starts, targets, free, None)
            if path is None or len(path) * RES > STUB_MAX:
                continue
            ok = [free[k] | starts[k] | targets[k] for k in range(NL)]
            runs, _ = self.runs(path, ok)
            runs[0][1].insert(0, tuple(pad["center"]))
            plane = g.nx * g.ny
            r, c = divmod(path[-1] % plane, g.nx)
            new_via = [] if tied[li][r, c] else [g.xy(r, c)]
            if not new_via:
                self.anchor_end(net, runs[-1])
            self.commit(net, nid, runs, new_via, width, None)
            pad["mask"].orin(tied[li])
            return True
        if record:
            self.failed.append(f"{net}: {pad['ref']}.{pad['num']} (plane)")
        return False

    def tie_planes(self, refs=None):
        """Tie plane-net SMD pads to their plane. refs: only these footprints (None: the rest)."""
        g = self.g
        for net in PLANES:
            if net not in self.plane_copper:
                tied = np.zeros((NL, g.ny, g.nx), bool)
                self.plane_copper[net] = tied
                for p in self.pads:
                    if p["net"] == net and p["pth"]:
                        for li in range(NL):
                            p["mask"].orin(tied[li])
                for p in self.pads:      # SMD pads that overlap a PTH pad of the net (thermal pads with vias)
                    if p["net"] == net and not p["pth"] and any(
                            q["pth"] and q["ref"] == p["ref"] and q["net"] == net and self.touch(p, q)
                            for q in self.pads):
                        for li in self.pad_layers(p):
                            p["mask"].orin(tied[li])
            tied = self.plane_copper[net]
            nid = self.ids[net]
            pads = [p for p in self.pads if p["net"] == net and not p["pth"] and not p.get("tied")
                    and (p["ref"] in refs if refs is not None else True)]
            # neighbouring pads of one part are joined directly, like AGND to GND under a QFN
            group = {id(p): {id(p)} for p in pads}
            for p in pads:
                for q in pads:
                    if q is p or id(q) in group[id(p)]:
                        continue
                    # pads of one part, or of neighbouring parts in a row (pull-ups to 3.3 V)
                    if math.dist(p["center"], q["center"]) > (1.6 if q["ref"] == p["ref"] else 2.0):
                        continue
                    if self.join_straight(net, nid, p, q):
                        merged = group[id(p)] | group[id(q)]
                        for k in merged:
                            group[k] = merged
            byid = {id(p): p for p in pads}
            seen = set()
            for p in sorted(pads, key=lambda p: p["mask"].area()):
                if id(p) in seen:
                    continue
                members = [byid[k] for k in group[id(p)]]
                seen |= group[id(p)]
                if any((self.pad_mask_layers(m) & tied).any() for m in members):
                    ok = True
                else:
                    ok = any(self.plane_stub(net, m, self.net_maps(nid), record=False) for m in members)
                if not ok:
                    self.failed.append(f"{net}: {p['ref']}.{p['num']} (plane)")
                for m in members:
                    m["tied"] = True

    def join_straight(self, net, nid, p, q):
        """A straight track between two pads of one net, if it keeps clear of everything else."""
        g = self.g
        common = [li for li in self.pad_layers(p) if li in self.pad_layers(q)]
        if not common:
            return False
        li = common[0]
        width = PLANE_WIDTHS[-1]
        free = self.free(self.net_maps(nid), width, self.clear(net))[li].copy()
        p["mask"].orin(free)
        q["mask"].orin(free)
        a, b = g.rc(*p["center"]), g.rc(*q["center"])
        n = max(abs(b[0] - a[0]), abs(b[1] - a[1]), 1)
        for k in range(n + 1):
            r = round(a[0] + (b[0] - a[0]) * k / n)
            c = round(a[1] + (b[1] - a[1]) * k / n)
            if not free[r, c]:
                return False
        self.commit(net, nid, [[li, [tuple(p["center"]), tuple(q["center"])]]], [], width, None)
        return True

    def pad_mask_layers(self, p):
        g = self.g
        m = np.zeros((NL, g.ny, g.nx), bool)
        for li in self.pad_layers(p):
            p["mask"].orin(m[li])
        return m


def rip_up(router, net):
    """Remove a net's tracks and vias so it can be routed again."""
    g = router.g
    nid = router.ids[net]
    track = (g.owner == nid) & (router.pad_owner != nid)
    g.owner[track] = router.pad_owner[track]
    router.tracks = [t for t in router.tracks if t["net"] != net]
    router.vias = [v for v in router.vias if v["net"] != net]
    router.geo.pop(net, None)
    g.drill = g.npth.copy()
    for p in router.pads:
        if p.get("drill"):
            g.drill |= g.disk(p["center"][0], p["center"][1], p["drill"] / 2)
    for v in router.vias:
        g.drill |= g.disk(v["x"], v["y"], VIA_DRILL / 2)


def blockers(router, pad):
    """Nets whose tracks sit in front of a pad."""
    g = router.g
    found = set()
    cx, cy = pad["center"]
    rad = EXIT_LEN_REF.get(pad["ref"], EXIT_LEN) + 0.8
    near = g.disk(cx, cy, rad)
    inv = {v: k for k, v in router.ids.items()}
    for li in router.pad_layers(pad):
        mine = near & (router.exits[li] == pad["id"])
        mine = ndimage.binary_dilation(mine, iterations=4)
        own = g.owner[li][mine & (g.owner[li] != router.pad_owner[li])]
        for o in np.unique(own):
            n = inv.get(int(o))
            if n and n != pad["net"] and n not in PLANES and not n.startswith("__nc"):
                found.add(n)
    return found


def retry_failed(router):
    """Second pass for what failed: cheaper vias and In2, a longer search."""
    global VIA_COST, MAX_EXPAND, TURN_COST, EXIT_COST
    VIA_COST, MAX_EXPAND, TURN_COST, EXIT_COST = 10.0, 12_000_000, 1.0, 1.0
    LAYER_COST[2] = 1.0
    todo = list(router.retry)
    for net, nid, pad in todo:
        tree, done = router.trees[net]
        if router.connect(net, nid, pad, tree, done, router.net_maps(nid)):
            done.append(pad)
            continue
        ripped = sorted(blockers(router, pad))[:4]
        if not ripped or not rip_and_route(router, net, nid, pad, ripped):
            router.failed.append(f"{net}: {pad['ref']}.{pad['num']}")


def rip_and_route(router, net, nid, pad, ripped):
    """Rip up the blocking nets, route the pad, route them again; undo all of it unless everything fits."""
    g = router.g
    snap = (g.owner.copy(), g.drill.copy(), list(router.tracks), list(router.vias),
            {k: {"segs": list(v["segs"]), "vias": list(v["vias"])} for k, v in router.geo.items()},
            {k: (t.copy(), list(d)) for k, (t, d) in router.trees.items() if k in ripped or k == net})
    for b in ripped:
        rip_up(router, b)
    tree, done = router.trees[net]
    ok = router.connect(net, nid, pad, tree, done, router.net_maps(nid))
    if ok:
        done.append(pad)
        router.retry = []
        for b in ripped:
            router.route_net(b)
        for bnet, bnid, bpad in router.retry:
            btree, bdone = router.trees[bnet]
            if router.connect(bnet, bnid, bpad, btree, bdone, router.net_maps(bnid)):
                bdone.append(bpad)
            else:
                ok = False
                break
        router.retry = []
    if not ok:
        g.owner[...] = snap[0]
        g.drill[...] = snap[1]
        router.tracks, router.vias = snap[2], snap[3]
        router.geo = snap[4]
        router.trees.update(snap[5])
    return ok


def retry_planes(router):
    """Plane stubs that found no via spot nearby get a longer reach."""
    global STUB_MAX
    STUB_MAX = 6.0
    todo = [f for f in router.failed if f.endswith("(plane)")]
    router.failed = [f for f in router.failed if not f.endswith("(plane)")]
    for f in todo:
        net, rest = f.split(": ")
        ref, num = rest.split(" ")[0].split(".")
        pad = next(p for p in router.pads if p["ref"] == ref and p["num"] == num and p["net"] == net)
        if router.plane_stub(net, pad, router.net_maps(pad["id"]), record=False):
            continue
        tied = router.plane_copper[net].copy()          # reach the nearest copper already on the plane
        if not router.connect(net, pad["id"], pad, tied, [], router.net_maps(pad["id"])):
            router.failed.append(f)


def finish(src, routes_in, dst, todo):
    """Keep a finished result and only try to connect the listed pads ("NET:REF.NUM"), as freely as possible."""
    global VIA_COST, MAX_EXPAND, TURN_COST, EXIT_COST
    VIA_COST, MAX_EXPAND, TURN_COST, EXIT_COST = 5.0, 20_000_000, 0.5, 0.0
    LAYER_COST[2] = 1.0
    geom = json.load(open(src))
    router = Router(geom)
    g = router.g
    old = json.load(open(routes_in))
    for t in old["tracks"]:
        li = LAYERS.index(t["layer"])
        router.commit(t["net"], router.ids[t["net"]], [[li, [tuple(p) for p in t["pts"]]]], [], t["w"], None)
    for v in old["vias"]:
        router.commit(v["net"], router.ids[v["net"]], [], [(v["x"], v["y"])], VIA_D, None)
    failed = []
    for item in todo:
        net, rest = item.split(":")
        ref, num = rest.split(".")
        pad = next(p for p in router.pads if p["net"] == net and p["ref"] == ref and p["num"] == num)
        nid = pad["id"]
        tree = (g.owner == nid).copy()
        if net in PLANES:      # a plane net counts as joined only at its vias and through-hole pads
            tree[...] = False
            for x, y in router.geo.get(net, {"vias": []})["vias"]:
                tree |= g.disk(x, y, VIA_D / 2)[None]
            for q in router.pads:
                if q["net"] == net and q["pth"]:
                    for li in range(NL):
                        q["mask"].orin(tree[li])
        for li in router.pad_layers(pad):
            view = tree[li, pad["mask"].r0:pad["mask"].r1, pad["mask"].c0:pad["mask"].c1]
            view[pad["mask"].sub] = False
        width = router.widths(net)[-1]
        free = router.free(router.net_maps(nid), width, router.clear(net))
        targets = tree & np.stack(free)
        others = [q for q in router.pads if q["net"] == net and q is not pad]
        if router.connect(net, nid, pad, targets, others, router.net_maps(nid)):
            continue
        router.trees[net] = (targets, others)
        ripped = sorted(blockers(router, pad))[:4]
        if not ripped or not rip_and_route(router, net, nid, pad, ripped):
            failed.append(item)
    json.dump({"tracks": router.tracks, "vias": router.vias, "failed": failed}, open(dst, "w"))
    print(f"finish: tracks {len(router.tracks)}, vias {len(router.vias)}, failed {failed}")


def main(src, dst, order="short"):
    geom = json.load(open(src))
    router = Router(geom)
    nets = sorted({p["net"] for p in geom["pads"] if p["net"]})
    power_first = ["/VSYS", "/VBUS", "/VBAT", "/REG_L1", "/REG_L2", "/EPD_SW", "/EPD_3V3"]

    def span(net):
        cs = [p["center"] for p in geom["pads"] if p["net"] == net]
        return (max(c[0] for c in cs) - min(c[0] for c in cs)) + (max(c[1] for c in cs) - min(c[1] for c in cs))

    # signals on fine-pitch parts go first, before power tracks crowd their pins
    fine = {"U2", "J3", "J1", "U6", "U4"}
    early = sorted({p["net"] for p in geom["pads"] if p["ref"] in fine and p["net"]} - set(power_first) - set(PLANES),
                   key=span)
    # USB-C has D-, D+, D-, D+ in one row: D- joins outwards first, so D+ can still leave under the receptacle
    early = ["/USB_DN", "/USB_DP"] + [n for n in early if n not in ("/USB_DN", "/USB_DP")]
    # the screen's supply rails leave the FPC first; its signals find their way around them
    # PREVGL and PREVGH cross the whole FPC fan-out to the booster, so they pick their way first
    rails = ["/EPD_PREVGL", "/EPD_PREVGH", "/EPD_3V3", "/EPD_VDD", "/EPD_VCOM", "/EPD_VSL", "/EPD_VSH1", "/EPD_VSHR"]
    early = rails + [n for n in early if n not in rails]
    power_first = [n for n in power_first if n not in rails]
    rest = sorted((n for n in nets if n not in power_first and n not in PLANES and n not in early), key=span,
                  reverse=(order == "long"))
    router.tie_planes(refs=fine)
    for net in early + power_first + rest:
        router.route_net(net)
    retry_failed(router)
    router.tie_planes()
    retry_planes(router)
    json.dump({"tracks": router.tracks, "vias": router.vias, "failed": router.failed}, open(dst, "w"))
    print(f"order {order}: tracks {len(router.tracks)}, vias {len(router.vias)}, failed {len(router.failed)}")
    for f in router.failed:
        print("  failed", f)


if __name__ == "__main__":
    if sys.argv[1] == "finish":       # finish geom.json routes.json out.json NET:REF.NUM ...
        finish(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
    else:
        main(*sys.argv[1:4])
