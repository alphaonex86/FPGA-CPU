#!/usr/bin/env python3
"""Routing search (operator 2026-11-08 / 2026-11-11): several routing tools, one after the other, each
on its own unrouted copy of the board (the generated copper only: locked) with the same budget (HOURS:
5 days at autoroute.CPUS CPUs); the boards one after the other. A tool works in rounds from its best
board: a supervised router run sized for ~ROUND_S, the DRC clean-up, close_route.py. It ends at 0 open
connections, at its budget, or stalled (STALL rounds without a gain: more budget buys nothing). The
board left with the fewest open connections is kept; a complete one gets its generator's --finish
step (FINISH). Every tool ending above 0 is never the budget: look for a routing-setup fault (e.g.
the routing order) or a fault outside routing (e.g. placement).
The state is saved after every round (route/search.json): a restart goes on where it stopped; a board
whose pads, planes or generated copper changed starts afresh. The board itself is only written at the
end; the rounds work on route/<board>.kicad_pcb.

Usage: route_search.py <board.kicad_pcb>...            route (claude-route.slice, one script at a time)
       route_search.py --service <board.kicad_pcb>...  the same as the user service fpgacpu-route: goes
                                                       on after a reboot (journalctl --user -u fpgacpu-route)
       route_search.py --status <board.kicad_pcb>...   each tool's state
Output: the board; route/search-start.kicad_pcb (the unrouted copy), route/tool-<k>.kicad_pcb (each
tool's best), route/search.log.
Exit 2 when a board keeps open connections.
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import pcbnew

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autoroute as ar
import close_route

HOURS = 120                               # per tool and board
ROUND_S = 3600
STALL = 3
CLOSE_MAX = 40                            # close_route.py (A* in Python) only on a board this close
UNIT = "fpgacpu-route.service"
FINISH = {"socket3-cyclonev": "gen_socket3_t8.py", "socket7-cyclonev": "gen_socket7_t8.py",
          "slot1-c2mu": "gen_c2mu_s8.py"}


def signature(board):
    """hash of what routing never changes: every pad's net and spot, the locked copper, the planes"""
    xy = lambda v: f"{v.x} {v.y}"
    lines = [f"{f.GetReference()} {p.GetNumber()} {p.GetNetname()} {xy(p.GetPosition())}"
             for f in board.GetFootprints() for p in f.Pads()]
    lines += [f"{t.GetNetname()} {xy(t.GetStart())} {xy(t.GetEnd())} {t.GetLayer()}"
              for t in board.GetTracks() if t.IsLocked()]
    for z in board.Zones():
        box = z.GetBoundingBox()          # kept: the vectors of a temporary box are freed memory
        lines.append(f"{z.GetNetname()} {z.GetLayer()} {box.GetX()} {box.GetY()} {box.GetWidth()} {box.GetHeight()}")
    return hashlib.sha1("\n".join(sorted(lines)).encode()).hexdigest()


def replace(src, dst):
    """copy src over dst in one step: a kill never leaves half a file"""
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copy(src, tmp)
    os.replace(tmp, dst)


def search(path):
    """route one board; True when it is complete"""
    route = path.parent / "route"
    route.mkdir(exist_ok=True)

    def note(text):
        with open(route / "search.log", "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
        print(text, flush=True)

    work, start, state_file = route / path.name, route / "search-start.kicad_pcb", route / "search.json"
    if ar.drc(path) == (0, 0):
        note(f"{path.name}: complete already")
        return True
    board = pcbnew.LoadBoard(str(path))
    for t in [t for t in board.GetTracks() if not t.IsLocked()]:
        board.Delete(t)
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    if state.get("signature") != signature(board) or not start.exists():
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(start), board)
        state = {"signature": signature(board), "tools": {}}
        note(f"start: {path.name} from its unrouted copy")
    for ext in (".kicad_pro", ".kicad_dru"):                                       # the DRC rules
        shutil.copy(path.with_suffix(ext), work.with_suffix(ext))
    signal = [k for k, L in enumerate(close_route.copper_layers(board)) if board.GetLayerType(L) != pcbnew.LT_POWER]
    jobs = ar.routers({f"layer {k} x2": f"{k}:2" for k in signal})
    note(f"{path.name}: {len(jobs)} tools x {HOURS} h at most, {ar.CPUS} CPUs, signal layers {signal}")
    for k, job in enumerate(jobs):
        tool = state["tools"].setdefault(job[0], {"seconds": 0, "rounds": 0, "idle": 0, "open": None, "passes": 1,
                                                  "end": None})
        best = route / f"tool-{k}.kicad_pcb"
        while tool["end"] is None:
            began = time.time()
            shutil.copy(start if tool["open"] is None else best, work)
            board = pcbnew.LoadBoard(str(work))
            n = ar.freerouting(board, work, [job], tool["passes"], HOURS * 3600 - tool["seconds"])
            if n is None:
                tool["passes"], text = max(1, tool["passes"] // 2), "no result"
            else:
                n, dropped = ar.settle(board, work)
                closed = 0
                if 0 < n <= CLOSE_MAX:
                    closed, _ = close_route.close(board, ar.drc_report(work))
                    n, dropped = ar.settle(board, work)
                per_pass = ar.pass_seconds(route / f"{work.stem}-0.log")
                text = f"{tool['passes']} passes, {n} open ({dropped} dropped, close_route {closed})"
                if per_pass:
                    tool["passes"] = max(1, min(1000, int(ROUND_S / per_pass)))
            if n is not None and (tool["open"] is None or n < tool["open"]):
                replace(work, best)
                tool["open"], tool["idle"] = n, 0
            else:
                tool["idle"] += 1
            tool["rounds"] += 1
            tool["seconds"] += time.time() - began
            tool["end"] = "complete" if tool["open"] == 0 else "budget" if tool["seconds"] >= HOURS * 3600 else \
                "stalled" if tool["idle"] >= STALL else None
            state_file.with_suffix(".tmp").write_text(json.dumps(state, indent=1))
            os.replace(state_file.with_suffix(".tmp"), state_file)
            note(f"{job[0]} round {tool['rounds']}: {text}; best {tool['open']}, {tool['seconds'] / 3600:.1f} h"
                 + (f": {tool['end']}" if tool["end"] else ""))
        if tool["open"] == 0:
            break
    done = {k: state["tools"][job[0]]["open"] for k, job in enumerate(jobs)
            if state["tools"].get(job[0], {}).get("open") is not None}
    if not done:
        sys.exit(f"FAIL: {path.name}: every tool failed")
    k = min(done, key=done.get)
    replace(route / f"tool-{k}.kicad_pcb", path)
    if done[k]:
        note(f"{path.name}: {done[k]} open; every tool left connections open: a routing-setup or placement "
             "fault, not the budget")
        return False
    r = subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name(FINISH[path.stem])), "--finish"],
                       capture_output=True, text=True)
    note(f"{path.name}: complete ({jobs[k][0]}); {FINISH[path.stem]} --finish exit {r.returncode}: "
         + (r.stdout + r.stderr).strip().splitlines()[-1])
    return r.returncode == 0


def service(boards):
    """the search as a user service in claude-route.slice (CPUS CPUs for all of it), restarted after a
    failure (5 times an hour at most) or a reboot"""
    unit = ar.claude_slice.UNITS / UNIT
    unit.write_text(f"""[Unit]
Description=FPGA-CPU routing search
StartLimitIntervalSec=3600
StartLimitBurst=5

[Service]
Slice={ar.claude_slice.child_slice("route", ar.CPUS)}
ExecStart={sys.executable} {pathlib.Path(__file__).resolve()} {' '.join(boards)}
Restart=on-failure
RestartSec=60
SuccessExitStatus=2

[Install]
WantedBy=default.target
""")
    for cmd in (["daemon-reload"], ["enable", UNIT], ["restart", UNIT]):
        subprocess.run(["systemctl", "--user"] + cmd, check=True)
    print(f"started {UNIT}: journalctl --user -u {UNIT}; systemctl --user stop {UNIT}")


def status(paths):
    for path in paths:
        state_file = path.parent / "route/search.json"
        print(path.name + ("" if state_file.exists() else ": no search yet"))
        for label, t in (json.loads(state_file.read_text())["tools"] if state_file.exists() else {}).items():
            print(f"  {label:16} {t['rounds']:4} rounds {t['seconds'] / 3600:6.1f} h  best {t['open']}  {t['end'] or 'running'}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = [pathlib.Path(a).resolve() for a in args]
    if not paths or any(p.stem not in FINISH or not p.exists() for p in paths):
        sys.exit(__doc__)
    if "--status" in sys.argv:
        return status(paths)
    if "--service" in sys.argv:
        return service([str(p) for p in paths])
    lock = ar.contain()
    complete = [search(p) for p in paths]
    lock.close()
    sys.exit(0 if all(complete) else 2)


if __name__ == "__main__":
    main()
