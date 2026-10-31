# Socket 370 + Cyclone V E A9 (5CEBA9/5CEFA9F23C8N) interposer power (plan/interposers.md task T3)

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
| VCC | core, periphery, PCS, PCIe hard IP digital | 1.07-1.13 V (typ 1.1 V, non-scrubbing part) | cvds p.8 Table 4 |
| VCC_AUX | auxiliary supply | 2.375-2.625 V (typ 2.5 V) | cvds p.8 Table 4 |
| VCCPD | I/O pre-driver | 2.5 V when VCCIO is 2.5/1.8/1.5/1.35/1.25/1.2 V; 3.3 V when VCCIO 3.3 | cvds p.8 Table 4 notes 4 |
| VCCIO | per bank | chosen per bank in T5: 2.5 V on the BCLK bank (R5), 3.3 V on default CMOS banks | cvds p.8-9 Table 4 |
| VCCPGM | configuration pins | 1.8/2.5/3.0/3.3 V band per chosen class | cvds p.9 Table 4 |
| VCCA_FPLL | PLL analog regulator supply | 2.375-2.625 V | cvds p.9 Table 4 |
| VCCBAT | battery back-up (volatile security key) | 1.2-3.0 V | cvds p.9 Table 4 |
| tRAMP | all supplies strictly monotonic, no plateaus | 200 us-100 ms (standard POR) | cvds p.9 Table 4 / p.69 Table 55 |


## Topology

```
12 V --[2 A fuse]--+--> SYNC BUCK --> 5 V intermediate
                   |                     |
                   |                     +--> SYNC BUCK --> 1.1 V core rail
                   |                     +--> aux rail
                   |                     +--> I/O rail
                   |
                   +--> (nothing else from 12 V)
```

Rail plan (regulator part numbers are T9 BOM items, no datasheets in repo):
- 12 V -> 5 V intermediate buck (2 A class).
- 5 V -> 1.1 V core buck (VCC), >= 3 A capable (power-up current reserve
  for the CV POR; exact current NM9).
- 5 V -> 2.5 V "aux rail" (VCC_AUX + VCCPD + VCCA_FPLL; ferrite-filtered
  branch to VCCA_FPLL), 500 mA LDO/buck class.
- 5 V -> 3.3 V "I/O rail" (translator high side + VCCIO of 3.3 V banks),
  1 A class.
- 5 V -> 1.8 V (VCCPGM), 300 mA class.
- VCCBAT: tied to the aux rail (band 1.2-3.0 V covers 2.5 V).


## Sequencing

All supplies strictly monotonic (200 us-100 ms ramp) [cvds p.9 Table 4];
CV does not define inter-rail groups in the datasheet, so the prototype
ramps everything from the intermediate rail with per-rail PGOOD cascade
(5 V first, then 3.3 -> 1.8 -> 2.5 -> core 1.1), and rely on the 4-12 ms
(fast) / 100-300 ms (standard) POR [cvds p.69 Table 55] before
configuration; CONF_DONE gating is T6's job (`hw/common/socket370_notes.md`
R6).


## Budget check (D1)

- D1 moved to external supply, so the socket 32 W budget no longer bounds
  the FPGA; the limit that applies is the AGENTS preference (< 10 W FPGA
  power) converted at ~85% buck efficiency: 12 V input draw stays below
  1.5 A
- Estimate - to be replaced by the vendor power estimator on real RTL
  (NM9, `hw/common/socket370_notes.md`): Cyclone V E A9 in this role (no transceivers, low-density logic)
  core ~1-2 W class + banks; all converted power < 10 W => true
- Connector sized 12 V / 2 A with 2 A fuse; AGENTS prefers FPGA < 10 W.
