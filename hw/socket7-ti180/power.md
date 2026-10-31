# Socket 7 + Efinix Ti180G400C3 interposer power (plan/interposers.md task T3)

Source per D1 (decided 2026-10-21 for socket 7, `plan/interposers.md`):
the interposer takes its power from the socket's own rails through the
Mill-Max header - VCC2 (core, 2.8 V on this board [spec p.5]) and VCC3
(I/O, 3.4 V on this board [spec p.5]). No external supply, no barrel jack.
No module RAM (D4). Page numbers are the printed pages of the cited PDFs
(`tids` excepted: verify per page).

Socket-side envelope ([notes] R2): VCC2 2.7/2.8/2.9 V +/-3.57 % on 25 pins,
VCC3 3.135-3.6 V on 28 pins, ICC2 max 6.5 A, ICC3 max 750 mA, active max
17.0 W [mmx p.31-32 Tables 10/12/13]. No VCC2/VCC3 sequencing: "no specific
power sequence required", both ON or both OFF within one second
recommended [mmx p.28 sec. 3.1.1.1]. Our loads are attached to rails the
board VRM raises together, so this holds by construction. All converter
outputs are strictly monotonic ramps (see Sequencing).

Sources:

| tag | file |
|---|---|
| cvds | FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf |
| tids | FPGAlist/Ti180_G400/docs/ti180_datasheet.pdf |
| mmx | sockets/socket7/pentium_mmx_datasheet_243185-004.pdf |
| fmb | sockets/socket7/intel_430hx_pcsiset_design_guide_297467-002.pdf |
| spec | sockets/socket7/board/biostar_mb-8500ttd_spec.pdf |
| jumpers | sockets/socket7/board/biostar_mb-8500ttd_undocumented_jumpers.pdf |
| mmpins | sockets/parts/mill-max_catalog_metric.pdf |
| notes | hw/common/socket7_notes.md |
| plan | plan/interposers.md |
| agents | AGENTS.md |

## Rails (Efinix Ti180G400C3)

| rail | where | required band | source |
|---|---|---|---|
| VCC | core (C3 speed grade) | 0.92-0.98 V (typ 0.95 V) | tids p.84 Table 62 |
| VCCA | PLL analog supply | 0.92-0.98 V, same rail as VCC | tids p.84 Table 62, p.79 Table 58 |
| VCCAUX | auxiliary supply | 1.75-1.85 V (typ 1.8 V) | tids p.84 Table 62 |
| VQPS | security fuse supply | tied low (stays low unless fuse blowing) | tids p.75 fuse note, p.76 note 1 |
| VCCIO | HSIO banks | unused on this design: tie per the unused-resources table | tids p.79 Table 58, p.84 Table 62 |
| VCCIO33 | HVIO banks | 3.3 V band (3.135-3.465 V) on every used bank: host bus and straps are 3.3 V TTL [notes R1] | tids p.84 Table 62 |
| VCC min transient | power-up momentum reserve | >= 1500 mA on VCC | tids p.79 Table 57 |
| tRAMP | all supplies | 0.1 x Vsupply/s to 10 V/ms | tids p.85 Table 63 |

## Topology

```
VCC2 2.8 V (25 header pins) --[bulk+bulk]--> SYNC BUCK --> VCC 0.95 V
                                                       +--> VCCA (PI filter)
VCC3 3.4 V board (28 header pins) --+--> VCCIO33 (direct)
                                    +--> 1.8 V aux (VCCAUX)
```

Rail plan (regulator part numbers are T9 BOM items; no regulator
datasheets in repo):
- VCC2 -> 0.95 V core buck, >= 3 A class honouring the 1.5 A power-up
  transient [tids p.79 Table 57]; input must tolerate the 2.70-2.90 V
  window at ~34 % duty (a 3-6 V input part does NOT qualify).
- core-rail output -> VCCA through a PI filter ("PLL VCCA: connect to
  VCC" is allowed [tids p.79 Table 58]).
- VCC3 -> 1.8 V aux (VCCAUX), 1 A class.
- VCC3 direct for VCCIO33: the board's 3.4 V is inside the 3.465 V band
  max [tids p.84 Table 62]; decouple per bank.
- Unused HSIO banks: VCCIO tied per the unused-resources table
  [tids p.79 Table 58]; VQPS tied low [tids p.76 note 1].

## Sequencing

- Group 1 (VCC, VCCA) ramps first, any order inside the group; group 2
  (VCCAUX, VCCIO33) starts >= 10 us after group 1 reaches 90 %;
  CRESET_N releases >= 10 us after all supplies reach 90 %, configuration
  starts after a 4.5 ms minimum delay [tids p.76-77 Figure 47 + steps
  2-6]. With VCC2/VCC3 rising together [mmx p.28], the group order is
  implemented as a PGOOD ripple: aux buck enable from VCC3 PGOOD feeds
  the group chain; the core buck leads via its own ramp.
- Ramp rates stay inside 0.1 x Vsupply/s to 10 V/ms [tids p.85 Table 63];
  the CRESET_N/CDONE handshake with CPURST is [notes] R6.

## Budget check (D1: total within the socket budget)

Numbers below are an **estimate** until the vendor power estimator runs on
real RTL (replaces this section then); this design uses no DDR PHY, no
transceivers and no HSIO/MIPI, so the class is "fabric + light I/O".

- Total interposer draw (estimate): core rail 4.0 W + I/O and aux
  2.0 W + converters at ~90 % efficiency => <= 7 W against the
  17.0 W the board VRM was built for [mmx p.32 Table 13; agents]. PASS.
- VCC2 branch (feeds only the 0.95 core buck): 1.6 A at
  2.8 V against ICC2 6.5 A [mmx p.31 Table 12]; 0.06 A average per
  VCC2 pin against the 1 A Mill-Max 550 rating [mmpins p.188-189]. PASS.
- VCC3 branch: VCCIO/VCCPD/VCCPGM direct + the aux buck:
  0.5 A estimate against ICC3 750 mA [mmx p.31 Table 12] - the
  binding limit of the three. PASS if the estimator confirms; if it comes
  back over, the VCCIO dynamic estimate must be refined per-bank before
  any rail re-planning.
- Board VCC3 sits at 3.4 V [spec p.5]: inside the 3.3 V band max 3.465 V
  of both FPGAs (tids p.84 Table 62) and inside VCC3 max 3.6 V [mmx p.31
  Table 10]. PASS.
- FMB rule "HCLK begins toggling within 150 ms after VCC reaches its
  operating level" [fmb p.2-2] is about the CPU seeing the clock: the
  board clock runs from power-on independent of our rails, and our
  converters start as soon as VCC2/VCC3 come up, so the FPGA is powered
  long before the board releases CPURST; the config-vs-reset timing is
  closed in [notes] R6.
- Ti180 power-up transient: VCC needs >= 1500 mA transient capability
  [tids p.79 Table 57]; the core buck is sized for it.
