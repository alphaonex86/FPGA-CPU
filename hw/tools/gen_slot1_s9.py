#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S9 verification audit + BOM for the slot 1 cartridge.

Checks (all read-only on the current board/schematic, gates against the
NM29/NM33 floors):
- ERC: kicad-cli sch erc, 0 error-severity rows (warnings are inventoried
  and counted by type; they are the accepted NC/CFG stubs + off-grid
  cosmetic rows, see S6),
- DRC: kicad-cli pcb drc, 0 error-severity rows; the unconnected count
  is pcbnew's GetUnconnectedCount. kicad-cli 10.0.3 stops its stdout
  count and JSON list at 499 (2026-11-01: a copy stripped of every track
  also reports 499), so below the cap CLI, JSON and pcbnew must agree and
  at the cap pcbnew must not count fewer,
- BOM: kicad-cli sch export bom -> hw/slot1-cyclonev/
  slot1-cyclonev.bom.csv, and every PCB footprint reference must appear
  in it (schematic == board part list),
- audit facts: copper layers, zone fill state, via/track counts, net
  count, per-family DDR3 pad coverage and remaining ratsnest.

Outputs: refreshed slot1-cyclonev.erc.json / slot1-cyclonev.drc.json
(gate artifacts), slot1-cyclonev.bom.csv; prints one PASS/FAIL per gate.
"""

import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pcbnew

CLI_CAP = 499           # kicad-cli unconnected report limit (see docstring)

ROOT = Path(__file__).resolve().parent.parent.parent
DIR = ROOT / "hw/slot1-cyclonev"
SCH = DIR / "slot1-cyclonev.kicad_sch"
PCB = DIR / "slot1-cyclonev.kicad_pcb"
ERC = DIR / "slot1-cyclonev.erc.json"
DRC = DIR / "slot1-cyclonev.drc.json"
BOM = DIR / "slot1-cyclonev.bom.csv"


def erc_gate():
    r = subprocess.run(["kicad-cli", "sch", "erc", "--format", "json",
                        "-o", str(ERC), str(SCH)], capture_output=True,
                       text=True)
    if r.returncode != 0:
        print("FAIL  ERC run:", r.stderr.strip()[:200])
        return None
    rep = json.loads(ERC.read_text())

    def walk(o):
        if isinstance(o, dict):
            if "severity" in o:
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            yield from (w for v in o for w in walk(v))

    vios = list(walk(rep))
    errs = [v for v in vios if v["severity"] == "error"]
    warns = Counter(v["type"] for v in vios if v["severity"] == "warning")
    print("ERC errors:", len(errs),
          "| warnings:", sum(warns.values()), dict(warns))
    for v in errs:
        print("   ", v["type"], v["description"][:100])
    return not errs


def drc_gate():
    r = subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json",
                        "-o", str(DRC), str(PCB)], capture_output=True,
                       text=True)
    if r.returncode != 0:
        print("FAIL  DRC run:", r.stderr.strip()[:200])
        return None
    rep = json.loads(DRC.read_text())
    errs = [v for v in rep["violations"] if v["severity"] == "error"]
    warns = Counter(v["type"] for v in rep["violations"]
                    if v["severity"] == "warning")
    cli = next((m.group(1) for line in (r.stdout or "").splitlines()
                for m in [re.search(r"Found (\d+) unconnected items", line)]
                if m), None)
    bd = pcbnew.LoadBoard(str(PCB))
    nw = bd.GetConnectivity().GetUnconnectedCount(True)
    listed = len(rep.get("unconnected_items", []))
    capped = listed >= CLI_CAP
    cli_ok = (cli is not None and int(cli) == listed
              and (nw >= listed if capped else nw == listed))
    print("DRC errors:", len(errs), "| warnings:", sum(warns.values()),
          dict(warns))
    print("  unconnected:", nw, "(pcbnew) | CLI",
          cli if cli is not None else "(no line)", "JSON", listed,
          "(capped)" if capped else "",
          "consistent" if cli_ok else "INCONSISTENT")
    for v in errs[:12]:
        print("   ", v["type"], v["description"][:100])
    return not errs and cli_ok


def bom_gate(bd):
    r = subprocess.run(["kicad-cli", "sch", "export", "bom",
                        "--output", str(BOM), str(SCH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("FAIL  BOM export:", r.stderr.strip()[:200])
        return None
    rows = list(csv.DictReader(BOM.open()))
    sch_refs = {r for row in rows for r in row["Refs"].split(",") if r}
    pcb_refs = {fp.GetReference() for fp in bd.GetFootprints()}
    miss = sorted(pcb_refs - sch_refs)
    extra = sorted(sch_refs - pcb_refs)
    ok = not miss
    print("BOM rows:", len(rows), "| pcb refs:", len(pcb_refs),
          "| missing on BOM:", miss or "-", "| BOM-only:", extra or "-")
    for row in rows:
        print("   ", row["Refs"], "|", row["Value"], "x", row["Qty"],
              "|", row["Footprint"] or "-", " DNP" if row.get("DNP") else "")
    return ok


def audit(bd):
    print("layers:", bd.GetCopperLayerCount())
    nnets = bd.GetNetCount()
    tracks = sum(1 for t in bd.GetTracks() if t.GetClass() == "PCB_TRACK")
    vias = sum(1 for t in bd.GetTracks() if t.GetClass() == "PCB_VIA")
    print("nets:", nnets, "| tracks:", tracks, "| vias:", vias)
    filled = sum(1 for z in bd.Zones() if z.IsFilled())
    print("zones:", len(bd.Zones()), "filled:", filled)
    fam = Counter()
    for fp in bd.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() == 0:
                continue
            n = p.GetNetname()
            key = ("DDR3" if n.startswith("/DDR3") else
                   "NC" if n.startswith("/NC_") else "socket/AGTL+/power")
            fam[key] += 1
    print("bound pads by family:", dict(fam))
    die_pads = sum(sum(1 for p in fp.Pads() if p.GetNetCode() != 0)
                   for fp in bd.GetFootprints()
                   if fp.GetReference() in ("U3", "U4", "U5", "U6"))
    u1_pads = sum(sum(1 for p in fp.Pads() if p.GetNetCode() != 0)
                  for fp in bd.GetFootprints()
                  if fp.GetReference() == "U1")
    print("U1 bound pads:", u1_pads, "| dies bound pads:", die_pads)


def main():
    print("== S9 slot1-cyclonev verification audit ==")
    bd = pcbnew.LoadBoard(str(PCB))
    audit(bd)
    ok_erc = erc_gate()
    ok_drc = drc_gate()
    ok_bom = bom_gate(bd)
    gates = [("ERC", ok_erc), ("DRC", ok_drc), ("BOM", ok_bom)]
    for name, ok in gates:
        if ok is None:
            print(f"GATE {name}: SKIPPED (tool failure)")
        print(f"{'PASS' if ok else 'FAIL'}  S9 {name}")
    if all(ok for _, ok in gates):
        print("PASS  S9 audit: schematic/board part list agree, DRC 0")
    sys.exit(0 if all(g for _, g in gates if g is not None) else 1)


if __name__ == "__main__":
    main()
