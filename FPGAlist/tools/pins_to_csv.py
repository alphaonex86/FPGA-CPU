#!/usr/bin/env python3
"""Vendor pin-out files -> one flat CSV per selected device and package:
ball, bank, function, config, vref, clock, pair, user_io. Run after ../../fetch.sh:

    python3 FPGAlist/tools/pins_to_csv.py

The user I/O count is checked against the vendor's resource tables
(Cyclone V overview Table 5: A9 F484 = 224 GPIO; Ti180 datasheet: G400 = 274).
"""
import csv
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIELDS = ["ball", "bank", "function", "config", "vref", "clock", "pair", "user_io"]


def cyclone_v(txt, package):
    """Altera pin table: one tab-separated section per package, each with its own
    header; some files repeat a package's section, which must then be identical."""
    sections, cols = [], None
    for line in open(txt, encoding="latin-1"):
        f = [c.strip().strip('"') for c in line.rstrip("\r\n").split("\t")]
        if f[0] == "Bank Number":
            cols = {name: i for i, name in enumerate(f)} if package in f else None
            if cols:
                sections.append([])
            continue
        if not cols or len(f) <= cols[package] or not f[cols[package]]:
            continue
        get = lambda k: f[cols[k]] if k in cols and cols[k] < len(f) else ""
        optional = get("Optional Function(s)")
        sections[-1].append(dict(ball=f[cols[package]], bank=get("Bank Number"), function=get("Pin Name/Function"),
                         config=get("Configuration Function"), vref=get("VREF"),
                         clock=",".join(o for o in optional.split(",") if o.strip().startswith("CLK")),
                         pair=get("Dedicated Tx/Rx Channel"),
                         user_io="1" if get("Pin Name/Function") == "IO" else "0"))
    if not sections or any(s != sections[0] for s in sections):
        sys.exit("ERROR: %s: %d %s sections, not one consistent table" % (txt, len(sections), package))
    return sections[0]


def xlsx_sheet(path, name):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    z = zipfile.ZipFile(path)
    target = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheet = next(s for s in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", ns) if s.get("name") == name)
    shared = ["".join(t.text or "" for t in si.iter("{%s}t" % ns["m"]))
              for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    for row in ET.fromstring(z.read("xl/" + target[sheet.get(rid)].replace("/xl/", ""))).iter("{%s}row" % ns["m"]):
        vals = {}
        for c in row.findall("m:c", ns):
            v = c.find("m:v", ns)
            if v is not None:
                vals[re.match(r"[A-Z]+", c.get("r")).group()] = shared[int(v.text)] if c.get("t") == "s" else v.text
        yield vals


def ti180(xlsx, sheet, package):
    rows, cols = [], None
    for r in xlsx_sheet(xlsx, sheet):
        if r.get("A") == "Bank Number":
            cols = {v: k for k, v in r.items()}
            continue
        if not cols or not r.get(cols[package]):
            continue
        get = lambda k: r.get(cols.get(k, ""), "")
        name = get("Pin Names")
        rows.append(dict(ball=r[cols[package]], bank=get("Bank Number"), function=name,
                         config=get("Configuration Functions"), vref=get("VREF Function for HSTL/SSTL"),
                         clock=get("Hard Block PLL REFCLK"), pair=get("LVDS and MIPI Pairs"),
                         user_io="1" if name.startswith("GPIO") else "0"))
    return rows


def write(path, rows, user_io):
    balls = [r["ball"] for r in rows]
    if len(set(balls)) != len(balls):
        sys.exit("ERROR: %s: duplicate balls" % path)
    n = sum(r["user_io"] == "1" for r in rows)
    if n != user_io:
        sys.exit("ERROR: %s: %d user I/O, the vendor resource table says %d" % (path, n, user_io))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (re.sub(r"\d", "", r["ball"]).rjust(2), int(re.sub(r"\D", "", r["ball"])))))
    print("%s: %d balls, %d user I/O" % (os.path.relpath(path, ROOT), len(rows), n))


def main():
    cv = os.path.join(ROOT, "CycloneV_A9", "pins")
    for dev in ("5ceba9", "5cefa9"):
        write(os.path.join(cv, dev + "_f484.csv"), cyclone_v(os.path.join(cv, dev + ".txt"), "F484"), 224)
    ti = os.path.join(ROOT, "Ti180_G400", "pins")
    write(os.path.join(ti, "ti180g400.csv"), ti180(os.path.join(ti, "ti180_pinout.xlsx"), "Ti180G400", "FBGA400"), 274)


if __name__ == "__main__":
    main()
