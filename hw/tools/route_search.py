#!/usr/bin/env python3
"""Long routing search on a board left with open connections by its T8 / S8 script (operator
2026-11-05: several systems, 5 days at most): rounds of freerouting (autoroute.py: the serial and the
parallel fork, one layer-cost variant per signal layer) with more passes than the T8 run (cycling
PASSES), then the DRC clean-up and close_route.py; a round leaving fewer connections open becomes the
best. Each round starts from the best board, every RESTART-th one from the board as given (a fresh
route with other passes). Stops at 0 open connections or at the deadline; the best board is written
back to the given path.

Usage: setsid nohup python3 hw/tools/route_search.py <board.kicad_pcb> [hours, default 120] &
       (on the board as gen_*_t8.py --pre or a partial T8 run left it)
Output: the board; route/search-start.kicad_pcb, route/search-best.kicad_pcb, route/search.log.
The vias of the routes keep their pads on every layer: rerun the board's thin_pads() before fab.
Exit 1 when connections stay open.
"""
import itertools
import pathlib
import shutil
import sys
import time

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autoroute as ar
import close_route

PASSES = (5, 20, 50, 100)
RESTART = 4


def main():
    path = pathlib.Path(sys.argv[1]).resolve()
    deadline = time.time() + 3600 * (float(sys.argv[2]) if len(sys.argv) > 2 else 120.0)
    route = path.parent / "route"
    route.mkdir(exist_ok=True)
    start, best_path, log = route / "search-start.kicad_pcb", route / "search-best.kicad_pcb", route / "search.log"

    def note(text):
        with open(log, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        print(text, flush=True)

    board = pcbnew.LoadBoard(str(path))
    signal = [k for k, L in enumerate(close_route.copper_layers(board)) if board.GetLayerType(L) != pcbnew.LT_POWER]
    jobs = ar.routers({f"layer {k} x2": f"{k}:2" for k in signal})
    best, _ = ar.settle(board, path)
    shutil.copy(path, start)
    shutil.copy(path, best_path)
    note(f"start: {path.name}, {best} open, {len(jobs)} routers per round, signal layers {signal}")
    for k in itertools.count():
        if best == 0 or time.time() > deadline:
            break
        passes = PASSES[k % len(PASSES)]
        origin = start if k % RESTART == RESTART - 1 else best_path
        shutil.copy(origin, path)
        board = pcbnew.LoadBoard(str(path))
        ar.freerouting(board, path, jobs, passes)
        n, dropped = ar.settle(board, path)
        if n:
            close_route.close(board, ar.drc_report(path))
            n, dropped = ar.settle(board, path)
        note(f"round {k}: from {origin.name}, {passes} passes: {n} open ({dropped} dropped), best {min(n, best)}")
        if n < best:
            best = n
            shutil.copy(path, best_path)
    shutil.copy(best_path, path)
    if best == 0:                     # complete: the generated ball vias no route uses go too
        note(f"dangling copper dropped: {ar.drop_dangling(pcbnew.LoadBoard(str(path)), path, keep_locked=False)}")
    errors, open_ = ar.drc(path)
    note(f"end: {open_} open, {errors} DRC errors; best board in {path.name}")
    if errors or open_:
        sys.exit(1)


if __name__ == "__main__":
    main()
