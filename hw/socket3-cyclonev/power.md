# Socket 3 + Cyclone V E A9 (5CEBA9/5CEFA9F23C8N) interposer power (plan/interposers.md task T3)

Source per D1 (decided 2026-10-31, `plan/interposers.md`): external 12 V
supply on the interposer. The socket's 23 VCC pins feed only the
VCORE-present detector divider (78.1 k, 44 uA at 3.45 V): the board's
PQ30RV21 LDO (2 A abs max, `hw/common/socket3_notes.md` R2) sees no other
load. The 28 VSS pins join the interposer GND (common reference for the
5 V TTL bus). No module RAM (D4). Page numbers are the printed pages of the
cited PDFs; regulator parts are the ones already on the FPGAmotherboard
boards (datasheets in `sockets/parts/`).

Socket-side nets: VOLDET (S4) is tied to VSS; the pull-ups (C11, DP3-DP0)
sit on the FPGA side of the switches (`hw/common/socket3_notes.md` R4/R6);
the 16 translators run from the 3.3 V rail (T5, D2) and stay open while the
socket rail is down: TLV6700 detector on V5 (`hw/tools/socket3_pdn.py`,
plan/interposers.md FPGAmotherboard compatibility).

Input: 12 V barrel jack CUI PJ-063AH (2.0 mm centre pin), centre-positive,
2 A fuse. All converter outputs are strictly monotonic ramps (see sequencing).

FPGA tags: cvds = `FPGAlist/CycloneV_A9/docs/cv_51002_device_datasheet.pdf`,
cvhb = `FPGAlist/CycloneV_A9/docs/cv_5v2_device_handbook_vol1.pdf`,
tids = `FPGAlist/Ti180_G400/docs/ti180_datasheet.pdf`.

## Rails

| rail | where | required band | source |
|---|---|---|---|
| VCC | core, periphery, PCS, PCIe hard IP digital | 1.07-1.13 V (typ 1.1 V, non-scrubbing part) | cvds p.8 Table 4 |
| VCC_AUX | auxiliary supply | 2.375-2.625 V (typ 2.5 V) | cvds p.8 Table 4 |
| VCCPD | I/O pre-driver | 2.5 V when VCCIO is 2.5/1.8/1.5/1.35/1.25/1.2 V; 3.3 V when VCCIO 3.3 | cvds p.8 Table 4 notes 4 |
| VCCIO | per bank | 3.3 V on every used bank 3B/4A/7A (T5 `pins.csv`, notes R5) | cvds p.8-9 Table 4 |
| VCCPGM | configuration pins | 3.3 V (band 1.8/2.5/3.0/3.3 V; host passive-serial levels, D7) | cvds p.9 Table 4 |
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

Rail plan (tps54620 = sockets/parts/ti_tps54620_6a_buck.pdf, tps62130 =
sockets/parts/ti_tps62130_3a_buck.pdf, jack = sockets/parts/cui_pj-063ah_barrel_jack.pdf):
- 12 V input: CUI PJ-063AH, 2.0 mm centre pin, rated 24 V / 8 A [jack p.1].
- 12 V -> 5 V intermediate: TPS54620, 4.5-17 V in, 6 A [tps54620 p.1].
- 5 V -> 1.1 V core (VCC): TPS62130, 3-17 V in, 3 A, 0.9-6 V out [tps62130
  p.1]. From 12 V the 1.1 V on-time (D/fsw = 37 ns at 2.5 MHz) would sit
  under its ~80 ns minimum on-time [tps62130 p.11]; from 5 V it is 88 ns,
  hence the intermediate rail.
- 5 V -> 2.5 V (VCC_AUX, VCCA_FPLL through a ferrite, VCCBAT): TPS62130.
- 5 V -> 3.3 V (VCCIO 3B/4A/7A, VCCPD, VCCPGM, 16 translators): TPS62130.
- VCCPD = 3.3 V because every used bank is 3.3 V [cvds p.8 Table 4 note 4];
  VCCPGM on the same rail: no 1.8 V regulator.


## Sequencing

All supplies strictly monotonic (200 us-100 ms ramp) [cvds p.9 Table 4].
Recommended order [cvhb p.10-4 Fig 10-3]: group 1 (VCC 1.1 V) to >= 80 %
before group 2 (VCCPGM, VCCIO, VCCPD, VCCA_FPLL, VCC_AUX) starts, VCCIO
together with VCCPD (else up to 1 A VCCPD / 250 mA VCCIO transients,
cvhb Table 10-1); VCCBAT any time. PGOOD cascade: 5 V first, its PGOOD
enables the core 1.1 V, whose PGOOD (92-98 % Vout rising [tps62130 p.5]) enables the 2.5 and 3.3 V
converters together; then the 4-12 ms (fast) / 100-300 ms (standard) POR
[cvds p.69 Table 55] before configuration; CONF_DONE gating is T6's job
(`hw/common/socket3_notes.md` R6).


## Budget check (D1)

- D1 is an external supply, so the DX4's 4.3 W socket budget no longer
  bounds the FPGA; the limit that applies is the AGENTS preference (< 10 W
  FPGA power) converted at ~85% buck efficiency: 12 V input draw stays below
  1.5 A, inside the 8 A jack [jack p.1] and the 6 A TPS54620
- Estimate - to be replaced by the vendor power estimator on real RTL
  (Quartus power estimate once T6 compiles): Cyclone V E A9 in this role (no transceivers) core ~1-2 W class
  + banks + 16 translators; all converted power < 10 W => true
- Connector sized 12 V / 2 A with 2 A fuse; AGENTS prefers FPGA < 10 W.
