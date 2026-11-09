#!/usr/bin/env python3
"""Routing search (operator 2026-11-08): several routers, one after the other, each on its own
unrouted copy of the board (the generated copper only: locked) with the same budget (hours at
autoroute.CPUS CPUs); each result goes through the DRC clean-up and close_route.py; the board left
with the fewest open connections is kept. All routers failing is never the budget: look for a
routing-setup fault (e.g. the routing order) or a fault outside routing (e.g. placement).
Runs in autoroute's memory / CPU slice; a second search waits for the first.

Usage: setsid nohup python3 hw/tools/route_search.py <board.kicad_pcb> [hours per router, default 4] &
       (on the board as gen_*_t8.py --pre left it, or any partial route of it)
Output: the board; route/search-start.kicad_pcb (the unrouted copy), route/search-best.kicad_pcb,
route/search.log. The vias of the routes keep their pads on every layer: rerun the board's
thin_pads() before fab.
Exit 1 when connections stay open.
"""
import pathlib
import shutil
import sys
import time

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autoroute as ar
import close_route

PASSES = 10000                            # the budget ends a run, not the passes


def main():
    lock = ar.contain()
    path = pathlib.Path(sys.argv[1]).resolve()
    hours = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    route = path.parent / "route"
    route.mkdir(exist_ok=True)
    start, best_path, log = route / "search-start.kicad_pcb", route / "search-best.kicad_pcb", route / "search.log"

    def note(text):
        with open(log, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        print(text, flush=True)

    board = pcbnew.LoadBoard(str(path))
    routed = [t for t in board.GetTracks() if not t.IsLocked()]
    for t in routed:
        board.Delete(t)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(start), board)
    signal = [k for k, L in enumerate(close_route.copper_layers(board)) if board.GetLayerType(L) != pcbnew.LT_POWER]
    jobs = ar.routers({f"layer {k} x2": f"{k}:2" for k in signal})
    note(f"start: {path.name}, {len(routed)} routed items dropped, {len(jobs)} routers x {hours} h, signal layers {signal}")
    best = None
    for job in jobs:
        shutil.copy(start, path)
        board = pcbnew.LoadBoard(str(path))
        if ar.freerouting(board, path, [job], PASSES, hours) is None:
            note(f"router {job[0]}: failed, see route/{path.stem}-0.log")
            continue
        n, dropped = ar.settle(board, path)
        closed = 0
        if n:
            closed, _ = close_route.close(board, ar.drc_report(path))
            n, dropped = ar.settle(board, path)
        note(f"router {job[0]}: {n} open ({dropped} dropped, close_route {closed}), best {n if best is None else min(n, best)}")
        if best is None or n < best:
            best = n
            shutil.copy(path, best_path)
        if best == 0:
            break
    if best is None:
        sys.exit("FAIL: every router failed")
    shutil.copy(best_path, path)
    if best == 0:                     # complete: the generated ball vias no route uses go too
        note(f"dangling copper dropped: {ar.drop_dangling(pcbnew.LoadBoard(str(path)), path, keep_locked=False)}")
    else:
        note("every router left connections open: a routing-setup or placement fault, not the budget")
    errors, open_ = ar.drc(path)
    note(f"end: {open_} open, {errors} DRC errors; best board in {path.name}")
    lock.close()
    if errors or open_:
        sys.exit(1)


if __name__ == "__main__":
    main()
