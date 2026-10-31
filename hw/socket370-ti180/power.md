# Socket 370 + Efinix Ti180G400C3 interposer power (plan/interposers.md task T3)

Source per D1 (decided 2026-10-20, `plan/interposers.md`): external supply on
the interposer; the socket rails stay untouched (the board's VRM still feeds
VCCCORE/VTT through the Mill-Max header, VID straps code <=1.7 V per the
operator). No module RAM (D4). Page numbers are the printed pages of the
cited PDFs.

Socket-side rails (unchanged by D1): VCCCORE straps to a code at or below
1.7 V; VTT 1.5 V AGTL+ is the board's termination/reference rail
(`hw/common/socket370_notes.md` R2/R3); VCCCMOS 1.5 V is generated inside
the package (`hw/common/socket370_notes.md` R4); EDGCTRL gets its 51 ohm
pull-up to the socket's VCCCORE; RTTCTRL/SLEWCTRL straps as in R4. These
are socket nets, not FPGA loads.

Input: 12 V barrel jack 5.5x2.1 mm, centre-positive, 2 A fuse. All
converter outputs are strictly monotonic ramps (see sequencing).

## Rails

| rail | where | required band | source |
|---|---|---|---|
| VCC | core (C3 speed grade part) | 0.92-0.98 V (typ 0.95 V) | tids p.84 Table 62 |
| VCCA | PLL analog power supply | 0.92-0.98 V (C3) | tids p.84 Table 62 |
| VCCAUX | auxiliary supply | 1.75-1.85 V (typ 1.8 V) | tids p.84 Table 62 |
| VQPS | security fuse supply | stays low unless fuse blowing; 1.71-1.89 V when used | tids p.75 fuse note, p.76 note 1, p.84 Table 62 |
| VCCIO | HSIO banks | 1.14-1.26 V for 1.2 V band ... 1.71-1.89 V for 1.8 V band; unused HSIO banks tie 1.2/1.35/1.5/1.8 V | tids p.84 Table 62, p.79 Table 58 |
| VCCIO33 | HVIO banks | 1.8/2.5/3.0/3.3 V bands (2.5 V on the BCLK bank per R5, 3.3 V CMOS banks) | tids p.84 Table 62 |
| VCC minimum transient | momentum reserve for power-up | >= 1500 mA transient on VCC | tids p.79 Table 57 |
| tRAMP | all supplies | 0.1xVsupply/s to 10 V/ms | tids p.85 Table 63 |


## Topology

```
12 V --[2 A fuse]--+--> SYNC BUCK --> 5 V intermediate
                   |                     |
                   |                     +--> SYNC BUCK --> 0.95 V core rail
                   |                     +--> aux rail
                   |                     +--> I/O rail
                   |
                   +--> (nothing else from 12 V)
```

Rail plan (regulator part numbers are T9 BOM items, no datasheets in repo):
- 12 V -> 5 V intermediate buck (2 A class).
- 5 V -> 0.95 V "core rail" buck (VCC), >= 3 A capable (honours the 1.5 A
  minimum power-up transient of tids p.79 Table 57 plus margin; exact
  current NM9).
- core-rail output -> VCCA through a PI filter (the unused-resources table
  allows "PLL VCCA: Connect to VCC" [tids p.79 Table 58]) - same rail
  value 0.92-0.98 V.
- 5 V -> 1.8 V "aux rail" (VCCAUX) and the VCCIO of all nine HSIO banks
  (HSIO stops at the 1.8 V band [tids p.84 Table 62]; T5 lands 15
  translator A sides there, unused HSIO banks tie 1.8 V [tids p.79 Table
  58]), buck class sized at T9 (NM9).
- 5 V -> 2.5 V and 3.3 V "I/O rails" for VCCIO33 banks (3.3 V also feeds
  the translator high side); BCLK bank TL at 2.5 V per R5.
- VQPS: tied low (must stay low unless fuse blowing [tids p.76 note 1]).


## Sequencing

Group 1 (VCC, VCCA) ramps first, any order within the group; group 2
(VCCAUX, VCCIO, VCCIO33) starts >= 10 us after group 1 reaches 90%; then
CRESET_N releases >= 10 us after all supplies reach 90%, and configuration
starts after a 4.5 ms minimum delay [tids p.76-77 Figure 47 + steps 2-6].
Implement with a shared PGOOD ripple: 5 V PGOOD -> core buck enable ->
VCCAUX enable chain; the FPGA's CRESET_N generation comes from the 1.8 V
rail supervisor and config logic of T6. Ramp rates inside
0.1xVsupply/s to 10 V/ms [tids p.85 Table 63].


## Budget check (D1)

- D1 moved to external supply, so the socket 32 W budget no longer bounds
  the FPGA; the limit that applies is the AGENTS preference (< 10 W FPGA
  power) converted at ~85% buck efficiency: 12 V input draw stays below
  1.5 A
- Estimate - to be replaced by the vendor power estimator on real RTL
  (NM9, `hw/common/socket370_notes.md`): Ti180 in this role (no DDR/MIPI; HSIO as 1.8 V GPIO)
  core ~2-4 W class + banks; all converted power < 10 W => true
- Connector sized 12 V / 2 A with 2 A fuse; AGENTS prefers FPGA < 10 W.
