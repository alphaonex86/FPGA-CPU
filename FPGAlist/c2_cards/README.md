# Slot 1 C2 bench: PCIe FPGA card (plan/slot1_c2.md)

The card holds the PCIe endpoint + BAR0 block (`sw/c2-vmm/bus.h`) and
drives the cable link to the Slot 1 cartridge (J5). An XC7A35T is enough
(free Vivado). All documents are kept here, versioned (seller links die
fast); `sources.txt` only records where each came from.

- `alinx/` AX7A035B user manual. On delivery, also save here the ALINX
  package sent with the board (schematic, XDC, demos).
- `xilinx/` XC7A35T FGG484 pin file; DS180/DS181 (Artix-7), UG470
  (configuration), UG471 (SelectIO), UG472 (clocking), UG475 (packages),
  UG482 (GTP), UG477 + PG054 v3.3 (PCIe integrated block / IP).
- `puzhi/` Puzhi product guides (the rejected candidate).
- Vivado 2025.2 (with Artix-7) is installed at
  `/mnt/data/perso/FPGA/AMD/` (`rtl/tools/vivado.sh`).

Purchase plan (operator 2026-11-02): one order around 2026-11-16, arrival
expected around 2026-12-16; AliExpress first, then Alibaba.

## Choice: ALINX AX7A035B (operator 2026-11-02) over Puzhi PZ-A735T-KFB

| | ALINX AX7A035B | Puzhi PZ-A735T-KFB |
|---|---|---|
| FPGA | XC7A35T-2FGG484I (core board AC7A035) | XC7A35T (core board PZ-A735T-SOM) |
| PCIe | 2.0 x2 (GTP, 100 MHz refclk from the slot) | 2.0 x2 (catalog) |
| link header | J11 40-pin 2.54 mm, pinout public (below); J13 unusable on the 35T (bank 13 not bonded) | 2 x 40-pin, pinout only in the docs sent after purchase |
| power | DC 12 V jack, or the PCIe slot 12 V, or ATX 12 V | DC 12 V / 1 A |
| JTAG | 10-pin 2.54 mm header (cable: ask, see below) | on-board "JTAG downloader" (catalog) |
| price seen | 299 USD ALINX list, 211 USD FPGA Pro, 357.90 EUR Botland (B2B only) | 239 USD Alibaba "Board", 279.99 USD Puzhi eBay store |
| official store | en.alinx.com; no AliExpress store confirmed | Puzhi eBay store; Alibaba seller is a trading firm |

The Puzhi card's header order is unknown until after purchase, and a
wrong order would put a link signal on a card supply pin. The cartridge
J5 can be laid out now against the ALINX J11 order.

## AX7A035B J11 (manual REV 1.1 sec. 3.11, `alinx/AX7A035B_user_manual.pdf`)

All I/O in bank 16, VCCO 3.3 V from an LDO (the LDO sets the level),
33 ohm in series on every I/O. Pin 1 GND, 2 +5 V, 37-38 GND, 39-40
+3.3 V. Pin names from `xilinx/xc7a35tfgg484pkg.txt`:

| J11 | ball | pin name | J11 | ball | pin name |
|---|---|---|---|---|---|
| 3 | G21 | IO_L24P_T3_16 | 4 | G22 | IO_L24N_T3_16 |
| 5 | C22 | IO_L20P_T3_16 | 6 | B22 | IO_L20N_T3_16 |
| 7 | F19 | IO_L18P_T2_16 | 8 | F20 | IO_L18N_T2_16 |
| 9 | D20 | IO_L19P_T3_16 | 10 | C20 | IO_L19N_T3_VREF_16 |
| 11 | A18 | IO_L17P_T2_16 | 12 | A19 | IO_L17N_T2_16 |
| 13 | B20 | IO_L16P_T2_16 | 14 | A20 | IO_L16N_T2_16 |
| 15 | F18 | IO_L15P_T2_DQS_16 | 16 | E18 | IO_L15N_T2_DQS_16 |
| 17 | E19 | IO_L14P_T2_SRCC_16 | 18 | D19 | IO_L14N_T2_SRCC_16 |
| 19 | C18 | IO_L13P_T2_MRCC_16 | 20 | C19 | IO_L13N_T2_MRCC_16 |
| 21 | B17 | IO_L11P_T1_SRCC_16 | 22 | B18 | IO_L11N_T1_SRCC_16 |
| 23 | D17 | IO_L12P_T1_MRCC_16 | 24 | C17 | IO_L12N_T1_MRCC_16 |
| 25 | A15 | IO_L9P_T1_DQS_16 | 26 | A16 | IO_L9N_T1_DQS_16 |
| 27 | B15 | IO_L7P_T1_16 | 28 | B16 | IO_L7N_T1_16 |
| 29 | A13 | IO_L10P_T1_16 | 30 | A14 | IO_L10N_T1_16 |
| 31 | E16 | IO_L5P_T0_16 | 32 | D16 | IO_L5N_T0_16 |
| 33 | C14 | IO_L3P_T0_DQS_16 | 34 | C15 | IO_L3N_T0_DQS_16 |
| 35 | F16 | IO_L2P_T0_16 | 36 | E17 | IO_L2N_T0_16 |

Link use (plan/slot1_c2.md "Cable link v0"): the up clock (cartridge ->
card) on J11 19 (MRCC); signals on odd pins 3-35 + pin 36; even pins
4-34 grounded on the cartridge, so the card bitstream must drive those
I/O low (never high: 3.3 V into ground through 33 ohm).

Other AX7A035B facts: DDR3 2 x MT41J256M16 (1 GB, x32), 128 Mb QSPI,
200 MHz + 125 MHz LVDS oscillators, PCIe RX0 D9/C9, RX1 B10/A10, TX0
D7/C7 (manual sec. 3.4).

## Ask the seller before paying

1. Package contents: JTAG cable (ALINX AL321 or a Xilinx Platform Cable
   USB clone) and 12 V adapter; otherwise add both to the same order. The
   AX7A035B also runs from the PC's PCIe slot power.
2. Puzhi only: the user manual / schematic with the 40-pin header order
   (Puzhi sends docs by Google Drive after purchase).
3. In the same order: a 1.27 mm 40-wire IDC ribbon cable (2 x 20 female
   both ends, 15-20 cm) and a 2 x 20 2.54 mm -> 1.27 mm adapter board (the
   cartridge J5 is a 1.27 mm header; plan/slot1.md D32 amendment).

The host PC needs a free slot the x4 edge fits (x4/x8/x16, or an x16
slot wired x1: the link then trains x1 Gen2, 500 MB/s, far above the
50 MB/s cable link). This dev host (Gigabyte B650 AORUS ELITE AX): GPU in
the CPU x16 slot; the chipset slots are x16 wired x1 and hold the BCM57810
(x8 card at x1) and likely the AX200 card: free one before bring-up. A
chipset slot adds a hop to the measured read latency (worst case).

## Re-check before purchase (2026-11-02)

Against manual REV 1.1: J11 order and bank-16 3.3 V (sec. 3.11), PCIe
pins + 100 MHz slot refclk (sec. 3.4), slot 12 V power (sec. 3.15),
sys clock R4/T4, key F15, LEDs, UART L15 all match `ax7a035b.xdc`;
`build.tcl` builds the x2 Gen2 IP on xc7a35tfgg484-2 with timing met.
Open until the schematic arrives: PERST# not on an FPGA pin (power-up
load ~24 ms < 100 ms; host resets reach the core as link down).
