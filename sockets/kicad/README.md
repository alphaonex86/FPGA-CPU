# Socket models (KiCad)

ZIF-socket footprints, symbols, STEP models and pin maps copied from
[FPGAmotherboard](https://github.com/alphaonex86/FPGAmotherboard). Their
generators are only in the operator's full tree, not the public repo:
`socket3/tools/gen_socket3_footprint.py` @a73daf8, `socket7/tools/gen_socket7_*.py`
@e84b442, `socket370/tools/gen_pga370_*.py` @57f3c94. `Socket3_Am5x86_237.step`
is the one regenerated in FPGAmotherboard on 2026-10-18 (the old one predated the
measured lever).

| Socket | ZIF footprint | CPU pins / holes | Pin map (source) | Symbol | ZIF body + lever |
|---|---|---|---|---|---|
| 3 | `Socket3_Am5x86_237` | 168 / 241 | `am5x86_pga168.csv` (AMD 19751C) | none yet | photo-scaled off the operator's MB-8433UUD-A, ±0.6 mm; top face 7.3 ±0.4 mm (photo, 2026-10-31; STEP still 8.0), hole depth 5 mm (caliper) |
| 7 | `Socket7_P55C_296` | 296 / 320 | `socket7_p55c.csv` (Intel 243185-004) | `CPU_Intel_Socket7` | assumed (PGA370 envelope), not measured |
| 370 | `PGA370_Socket_ZIF` | 370 / 370 | `pga370_coppermine.csv` (Intel 245264-008) | `CPU_Intel_PGA370` | Intel 244410-002 Fig. 1/2a |

## Interposer base

`python3 tools/gen_base.py` builds, per socket, the interposer's CPU-side pins:
a Mill-Max PGA header soldered under the board (catalog in
`../parts/mill-max_catalog_metric.pdf`, p.140 pins, p.137 insulator).

| Socket | Footprint | 3D model (built, not in git) | Check board (base on the ZIF) | Header | Drill / pad | Board above socket |
|---|---|---|---|---|---|---|
| 3 | `Interposer.pretty/Socket3_Base_PGA168` | `3dmodels/Socket3_Base_PGA168.step` | `socket3-base-check.kicad_pcb` | 551, pin #5503 | 0.90 / 1.50 mm | 6.40 mm |
| 7 | `Interposer.pretty/Socket7_Base_PGA296` | `3dmodels/Socket7_Base_PGA296.step` | `socket7-base-check.kicad_pcb` | 550, pin #5012 | 0.80 / 1.25 mm | 3.99 mm |
| 370 | `Interposer.pretty/Socket370_Base_PGA370` | `3dmodels/Socket370_Base_PGA370.step` | `socket370-base-check.kicad_pcb` | 550, pin #5012 | 0.80 / 1.25 mm | 3.99 mm |

- Pin positions come from the ZIF footprints (socket top view = interposer top
  view), so the base goes unmirrored on the interposer's F.Cu; the generator
  fails unless they match the pin map exactly.
- Male pin 0.48 x 3.91 mm (CPU: 0.43-0.51 x 3.05-3.30 mm); tails stand 1.6 mm
  (551) / 2.57 mm (550) above a 1.6 mm board. F.CrtYd is the tail ring, B.CrtYd
  the header insulator; F.Fab shows the original CPU package.
- Footprints load their 3D models from `${KIPRJMOD}/3dmodels/`; the check boards
  live here so that resolves.
- Not measured yet (see `plan/interposers.md` M1-M3): Socket 3/7 ZIF height (the
  STEPs use 8.0 mm), free space around each socket, header seating depth.
