# LattePanda Mu on the Slot 1 C2 cartridge: viability (2026-11-04)

Question: can the Mu (D40, plan/slot1_c2.md "Mu cartridge") sit on the
Slot 1 cartridge next to the XC7A100T, before the module is bought?

**Verdict: viable.** One deviation from the Intel envelope (the cartridge
PCB grows from 57.8 to ~75 mm high) and the module price are the two
points for the operator. No blocker found.

Sources (all in this folder unless noted): `design_guide_*.html` +
`hsio_multiplexing.html` (LattePanda carrier design guide),
`dimension_drawing.pdf`, `LattePanda_Module_H8.0mm_Horizontal.kicad_mod`,
`LattePanda_Mu_H8.0_Horizontal.step.7z` (solid bounding boxes measured
with OCCT DRAWEXE), `lotes_addr0110_sodimm_9.2h.pdf`,
`edge_connector_pinout.xlsx`, `bios_dflt_README.md`;
plan/slot1.md D16 (envelope); `FPGAlist/c2_cards/xilinx/ug475_7Series_Pkg_Pinout.pdf`.

## Mechanical

| check | need | have | result |
|---|---|---|---|
| width | socket + module courtyard 77.4 mm [H8 footprint F.CrtYd x +-38.7] | 95 mm between the retention bands (x 16..111) [D16/S7] | ok, 17.6 mm left for jack / USB / headers |
| height | 65.4 mm: socket back 5.2 + module 60.2 [H8 footprint F.CrtYd y -5.2..60.2] | 50.8 mm above the slot band (y 7.0..57.8) | **no**: PCB grows to >= 7.0 + 65.4 = 72.4 mm, ~75 mm with margin (+17 mm over Intel's 2.275 in) |
| overhang instead | - | the Mu's 2 M2 holes are 3 mm from the far edge [dimension drawing] and must be screwed to standoffs [design_guide_edge_connector] | not allowed: the far edge needs board under it |
| rotate 90 deg | 69.6 + 5.2 = 74.8 mm high | - | worse |
| thickness, primary side | socket 9.2H: standoff 6.6 mm, Mu PCB 1.2, active cooler FIT0981 19 mm [DFRobot] = ~26.8 mm (STEP with the 8.0H socket and the cooler: 25.4 mm) | Intel boxed envelope 32.8 mm [D16] | ok, ~6 mm spare |
| under the Mu | FGG484 2.60 mm max [UG475 Fig 4-16] + Mu bottom parts 2.0 mm max [design_guide_edge_connector; STEP 2.1] = 4.6 mm | gap = standoff height 6.6 mm (9.2H) / 5.5 mm (8.0H) [design_guide_edge_connector] | ok anywhere under the module (2.0 mm air with 9.2H) |

Consequences:

- Nearly every cartridge part goes under the Mu or on B.Cu: the free
  17.6 mm column is narrower than the 23 mm FPGA. Under the module:
  U1, the 7 x 16612 (TSSOP 1.2 mm), terminations, 0402s; tall inductors
  only where the Mu has no bottom part.
- The cartridge stands ~17 mm taller than an original one: nothing on
  an open bench; in a case, check the PSU / drive cage above the slot.
- Socket: LOTES ADDR0110-P005A, SODDR4 9.2H 260 STD (on LattePanda's
  recommended list; LCSC C962122, in stock, ~US$1), so it is in the same
  JLCPCB order. The TE 2309411-1 8.0H of the KiCad footprint is not at
  LCSC. The footprint is redrawn from the LOTES drawing AP-ADDR0110.
- Standoffs: M2, 6.6 mm +-0.1 [design_guide_edge_connector]; no exact
  LCSC part found yet (PEM SMTSO-M2 stops at 6 mm; Sinhoo SMT M2 series
  to check).
- FPGA thermal under the module: theta-JA 15.8 C/W still air
  (XC7A100T FGG484, UG475 Table 5-1). Estimated 2 W (to confirm with a
  Vivado power report) gives +32 C; with ~50 C air under the module,
  Tj ~82 C < 100 C (I grade). It works, but the margin is small: keep
  the design under 2 W, or put U1 on B.Cu if the D8 boards leave room
  behind the slot (bench M4).

## Electrical

- PCIe: the default BIOS sets HSIO8-11 to one PCIe 3.0 x4 [bios_dflt_README];
  the root port negotiates down to Gen2 (GTP limit) [design_guide_pcie].
  Board rules: 85 ohm differential, intra-pair skew < 5 mil, no inter-pair
  matching, P/N swap allowed (polarity inversion), **no lane reversal**,
  so Mu lane k goes to GTP lane k (X0Y(7-k)). On-board chip case: 0.22 uF
  on both directions, < 8 mm from the receiver side chip.
- REFCLK2 is bound to HSIO8 and is switched on "once the system detects a
  device presence" on HSIO8 [hsio_multiplexing]: the FPGA must be
  configured (GTP RX terminations up) before the Mu boots. Fallback without
  a custom BIOS: Chipset > PCH-IO > PCI Express > PCIE Clocks, Clock2
  assignment Enabled, Clkreq Disabled (forced output).
- Power-on: the Mu starts on a PWR_SW# low pulse >= 125 ms; the guide
  rejects relying on "restore on AC power loss" [design_guide_auto_power_on].
  Here the FPGA pulses PWR_SW# through an NMOS after DONE, so the order
  "FPGA configured -> Mu on -> PCIe enumeration" is fixed in hardware. RST_SW#
  works the same way (pulse >= 16 ms); PSON (weak, 0.33 mA) goes to an FPGA input as the
  Mu state [design_guide_pwctl_stat].
- Power: VIN 9-20 V (absolute 7.6-22.3 V, ripple <= 200 mV); N305 > 15 W
  plus the recommended 50 % margin = 22.5 W [design_guide_power]; fan
  5 V 0.35 A; FPGA side ~5 W (estimate). Total ~30 W: 12 V 3 A adapter.
  The Slot 1 has no 12 V (VCC_CORE, VCC_L2, VCC_VTT, one VCC5 pin
  [hw/common/slot1_signals.csv]), so a DC jack rated >= 3 A.
- RTC: the edge has an "RTC Battery Input"; without a cell, SLP_S4 and
  CMOS misbehave [design_guide_pwctl_stat FAQ]: coin cell on the cartridge.
- Access for installing and debugging the VMM: USB 2.0 ports 1-5, 7, 8 (P6 is
  reserved for Type-C by the default BIOS) [design_guide_usb_20], HDMI on
  DDIB, UART0 (GPP_H10/H11) [edge_connector_pinout.xlsx].
- Cartridge powered, board off: the FPGA / 16612 outputs must stay off
  until the slot rails are up (gate OE on a slot-power sense). This is a design
  item, not a blocker.

## Software

- The N305 / N100 (Gracemont cores) have VT-x with EPT and unrestricted
  guest: the KVM VMM (`sw/c2-vmm`) runs as on the development PC.
- The VMM runs one vCPU, so single-thread speed matters: N305 turbo
  3.8 GHz vs N100 3.4 GHz (~+12 %). Cores beyond 2-3 and RAM beyond the
  32-bit guest's 4 GB are not used: 8 GB is enough.
- Linux + VMM on the 64 GB eMMC. The Mu boots in tens of seconds; the
  agent starts the guest at the board's RESET# deassert, which the VMM
  waits for (board and cartridge powers are independent).

## Purchase (DFRobot store, 2026-11-04)

| item | SKU | price | stock |
|---|---|---|---|
| Mu N305, 16 GB, 64 GB eMMC | DFR1149 | US$599 (older listings: 269-299) | in stock |
| Mu N100, 8 GB, 64 GB eMMC | DFR1146 | US$359 | in stock |
| Mu N100, 16 GB, 64 GB eMMC | DFR1147 | US$499 | back order |
| Active cooler (69.6 x 50.4 x 19 mm, 5 V 0.35 A, PH2.0-4P) | FIT0981 | US$12 | in stock |
| Fanless heatsink | FIT0989 | US$7.90 | in stock |
| Lite carrier (HDMI, USB 3, Ethernet, PCIe x4, M.2) | DFR1142 | US$39 | in stock |

DFRobot takes PayPal; shipping to Bolivia is to be confirmed at checkout.
The Lite carrier is optional. It is not an external PC (it carries the same
Mu, only during bring-up). With it, Linux and the VMM can be installed on the
eMMC and KVM and the BIOS clock settings checked before the cartridge PCB exists.
