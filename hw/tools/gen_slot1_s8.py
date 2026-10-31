#!/usr/bin/env python3
"""Task S8 (plan/slot1.md): DDR3 byte-map fix-ups + nets on the S7 board.

Step A (this file): put the real MT41K512M16HA ball map [Fig 7 of the Micron
8Gb DDR3L datasheet, page 18; decoded into
hw/common/mt41k512m16ha_balls.csv] on the four die footprints in place of
the S7 generic 6x16 placeholder grid [NM25d], and give every pad the net
its S6 netlist node carries (comp ref == footprint ref; most pads carry the
netlist pin name verbatim, die pads are ball-coded and resolve through the
ball map).  Power pours come at S8b; tracks at S8c.

Checks (exit 1): every netlist node hits exactly one pad; every non-NC die
function maps into exactly one ball; pad nets equal the netlist nets; then
kicad-cli pcb drc --severity-error stays 0.
"""
import csv
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "hw/slot1-cyclonev"
BALLFILE = ROOT / "hw/common/mt41k512m16ha_balls.csv"

# symbol pin -> ball code renames (x16 names)
DIE_SYM_TO_BALL = {
    "CKp": "CK", "CKn": "CK#",
    "DQS0p": "LDQS", "DQS0n": "LDQS#",
    "DQS1p": "UDQS", "DQS1n": "UDQS#",
    "DM0": "LDM", "DM1": "UDM",
}
# ball code -> symbol pin renames: selectable functions on the datasheet
# plus the byte-lane prefixes the symbol carries per DQS/DM group
BALL_TO_SYM = {"A10/AP": "A10", "A12/BC#": "A12",
               "CK": "CKp", "CK#": "CKn",
               "LDQS": "DQS0p", "LDQS#": "DQS0n",
               "UDQS": "DQS1p", "UDQS#": "DQS1n",
               "LDM": "DM0", "UDM": "DM1"}


def load_netlist():
    """(num, name) list, (ref, pin) -> num, from the S6 net export"""
    text = (OUT / "slot1-cyclonev.net").read_text()
    nets, nodes = [], {}
    for m in re.finditer(
            r'\(net\n\s*\(code "(\d+)"\)\s*\(name "([^"]+)"\)((?:.|\n)*?)\n\t\t\)',
            text):
        num, name = int(m.group(1)), m.group(2)
        nets.append((num, name))
        for n in re.finditer(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"', m.group(3)):
            key = (n.group(1), n.group(2))
            assert key not in nodes, "node %s twice in the netlist" % (key,)
            nodes[key] = num
    return nets, nodes


def load_balls():
    rows = list(csv.DictReader(
        line for line in BALLFILE.read_text().splitlines()
        if not line.startswith("#")))
    pos = {r["ball"]: (float(r["x_mm"]), float(r["y_mm"])) for r in rows}
    code = {r["ball"]: r["code"] for r in rows}
    assert len(pos) == 96, len(pos)
    return pos, code


def pads_of(block):
    """[(start, end, text)] of every (pad ...) up to its balanced close"""
    out = []
    for m in re.finditer(r"\n\t+\(pad \"", block):
        i, d = m.start() + 1, 0
        j = i
        while True:
            if block[j] == "(":
                d += 1
            elif block[j] == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        out.append((i, j + 1, block[i:j + 1]))
    return out


def blocks_of(pcb):
    """[(start, end, ref, text)] for every footprint, balanced scan"""
    out = []
    for m in re.finditer(r"\n\t\(footprint \"", pcb):
        s = m.start() + 1
        d, i = 0, s
        while True:
            if pcb[i] == "(":
                d += 1
            elif pcb[i] == ")":
                d -= 1
                if d == 0:
                    break
            i += 1
        blk = pcb[s:i + 1]
        ref = re.search(r'fp_text reference "([^"]+)"', blk).group(1)
        out.append((s, i + 1, ref, blk))
    return out


def die_pads(ref, nodes, netname, balls, ballcode):
    """real ball pad list for a die footprint; also returns the
    electrical-pin -> ball map the audit uses"""
    sym_pins = {p for (r, p), _ in nodes.items() if r == ref}
    out, used = [], {}
    for ball in sorted(balls, key=lambda b: (balls[b][1], balls[b][0])):
        code = ballcode[ball]
        if code == "NC":
            continue
        cand = DIE_SYM_TO_BALL.get(code, BALL_TO_SYM.get(code, code))
        if cand in sym_pins:
            pin = cand
        elif code == "VDD" and sym_pins & {"VDD", "VDDQ"}:
            pin = "VDD" if "VDD" in sym_pins else "VDDQ"
        elif code == "VDDQ" and sym_pins & {"VDD", "VDDQ"}:
            pin = "VDDQ" if "VDDQ" in sym_pins else "VDD"
        elif code == "VSS" and sym_pins & {"VSS", "VSSQ"}:
            pin = "VSS" if "VSS" in sym_pins else "VSSQ"
        elif code == "VSSQ" and sym_pins & {"VSS", "VSSQ"}:
            pin = "VSSQ" if "VSSQ" in sym_pins else "VSS"
        else:
            raise AssertionError(
                "ball %s code %s unmapped into %s" % (ball, code, ref))
        power = code in ("VDD", "VDDQ", "VSS", "VSSQ")
        if not power:
            assert pin not in used, "%s %s on two balls (%s/%s)" % (
                ref, pin, used.get(pin), ball)
        used.setdefault(pin, ball)
        if not power:
            sym_pins.discard(pin)
        num = nodes[(ref, pin)]
        out.append('\t(pad "%s" smd circle (at %.2f %.2f) '
                   '(size 0.45 0.45) (layers "F.Cu" "F.Mask") '
                   '(net %d "%s"))'
                   % (ball, balls[ball][0], balls[ball][1], num,
                      netname[num]))
    leftover = sym_pins - {"VDD", "VDDQ", "VSS", "VSSQ"}
    assert not leftover, "%s pins without a ball: %s" % (ref, sorted(leftover))
    return out, used


def main():
    nets, nodes = load_netlist()
    netname = dict(nets)
    balls, ballcode = load_balls()
    pcb = (OUT / "slot1-cyclonev.kicad_pcb").read_text()
    if '(net 1 "' in pcb:
        raise SystemExit("FAIL: board already netted; S8a needs the fresh "
                         "S7 board (rerun gen_slot1_s7.py)")

    # ---- die footprints get the real ball lands ------------------------
    die_used = {}
    for ref in ("U3", "U4", "U5", "U6"):
        newpads, die_used[ref] = die_pads(ref, nodes, netname, balls, ballcode)
        head = None
        for (s, e, blk_ref, blk) in blocks_of(pcb):
            if blk_ref != ref or "DDR3" not in blk:
                continue
            head = blk[:re.search(r"\n\t+\(pad \"", blk).start() + 1]
            pcb = pcb[:s] + head + "\n" + "\n".join(newpads) + "\n\t)\n" + pcb[e:]
            break
        assert head is not None, ref

    # ---- board net blocks ----------------------------------------------
    pcb = pcb.replace('(net 0 "")\n',
                      '(net 0 "")\n' + "".join(
                          '\t(net %d "%s")\n' % (num, name)
                          for num, name in nets), 1)
    # reverse order: replacing a block shifts the offsets of everything
    # behind it, so late-first keeps the scanned positions valid
    for (s, e, ref, blk) in reversed(blocks_of(pcb)):
        if re.match(r"U[3-6]$", ref):
            continue                          # done via the ball map
        outblk = blk
        for (i, j, padtext) in reversed(pads_of(blk)):
            pnum = re.search(r'\(pad "([^"]*)"', padtext).group(1)
            num = nodes.get((ref, pnum))
            if num is not None:
                newpad = padtext.replace("(layers",
                                         '(net %d "%s") (layers'
                                         % (num, netname[num]), 1)
                outblk = outblk[:i] + newpad + outblk[j:]
        pcb = pcb[:s] + outblk + pcb[e:]

    # ---- audit ---------------------------------------------------------
    # pad text must carry the net the netlist node demands; die pads are
    # ball-coded so the check goes through the ball map generated above
    fails, seen = [], {}
    for (s, e, ref, blk) in blocks_of(pcb):
        for (i, j, padtext) in pads_of(blk):
            pnum = re.search(r'\(pad "([^"]*)"', padtext).group(1)
            netnum = re.search(r'\(net (\d+)', padtext)
            seen[(ref, pnum)] = int(netnum.group(1)) if netnum else 0
    for (ref, pin), num in nodes.items():
        pnum = die_used[ref][pin] if re.match(r"U[3-6]$", ref) else pin
        if (ref, pnum) not in seen:
            fails.append("node without a board pad: (%s, %s)" % (ref, pin))
        elif seen[(ref, pnum)] != num:
            fails.append("net mismatch (%s, %s): pad %d, want %d"
                         % (ref, pin, seen[(ref, pnum)], num))
    if fails:
        for f in fails:
            print("FAIL:", f)
        sys.exit(1)

    path = OUT / "slot1-cyclonev.kicad_pcb"
    path.write_text(pcb)

    # ---- the S7 DRC gate must survive netting ---------------------------
    # note: --exit-code-violations would also fail on *warnings* (the
    # unconnected ratsnest exists by design until S8c), so the gate reads
    # the JSON and fails on any severity==error violation
    r = subprocess.run(["kicad-cli", "pcb", "drc",
                        "--format", "json",
                        "-o", str(OUT / "slot1-cyclonev.drc.json"),
                        str(path)], capture_output=True, text=True)
    j = json.load(open(OUT / "slot1-cyclonev.drc.json"))
    errs = [v for v in j.get("violations", []) if v.get("severity") == "error"]
    if errs:
        print(f"DRC ERRORS ({len(errs)}):")
        for v in errs[:20]:
            print("  ", v.get("type"), str(v.get("description"))[:110])
            for it in v.get("items", [])[:2]:
                print("      -", str(it.get("description"))[:100])
        sys.exit(1)
    warn = len(j.get("violations", [])) - len(errs)
    print(f"PASS  S8a: {len(nets)} nets, {len(nodes)} nodes netted, "
          f"{len(seen)} board pads bound, DRC clean "
          f"({warn} warnings = the unconnected ratsnest for S8c)")


if __name__ == "__main__":
    main()
