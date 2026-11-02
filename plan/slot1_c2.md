# Slot 1 C2: N100 + FPGA PCIe <-> P6 bridge, implementation

Variant C2 of `slot1_variants.md` (decided best, D26): a host PC runs
Linux + KVM; one vCPU executes the board's stock BIOS and OS; every guest
access outside its RAM is a bus cycle on the Slot 1 board. Test boards per
slot1 D8 (440BX first).

Shape (D31, no single-source part): any x86 PC with VT-x/AMD-V (the VMM
runs on this Ryzen host already; an N100 mini-PC for the compact build)
-> PCIe -> any FPGA PCIe card (Puzhi PZ-A7200T-KFB, ALINX AX7A200B,
Cyclone V GX kits...: vendor PCIe IP in a thin wrapper) -> a cable link ->
the variant A Slot 1 cartridge (Cyclone V A9, P6 bus agent on its
AGTL+ translators). The cartridge is the only custom board and serves A
too. Nothing is bought before the viability verdict below.

## Parts

| part | where | status |
|---|---|---|
| VMM (KVM, one vCPU, bus backends) | `sw/c2-vmm/` | v0 + 440BX shadow RAM: test ROM passes on the sim backend |
| BAR0 bus protocol | `sw/c2-vmm/bus.h` | v0 defined |
| PCIe card: endpoint + BAR0 block -> cable link | `rtl/c2/` (vendor-neutral, PCIe IP wrapper) | to do |
| Cable link protocol (card <-> cartridge) | `rtl/c2/`; 22 cartridge balls (D32: 17 at 3.3 V, 2 at 1.35 V, 3 free) | to do |
| Cartridge PCB: link header + 19 selection 0-ohms (D32) | `hw/slot1-cyclonev` generators | to do |
| Cartridge: link + P6 bus agent (AGTL+ cycles, snoop stall, DMA mirror) | `rtl/c2/` on the A cartridge | to do |
| Bench: host <-> PCIe card round trip | hardware | after the verdict |

## VMM v0 (`sw/c2-vmm`, `test.sh`)

- Guest RAM: 0-0x9ffff and 1 MB up (option `-m`, default 256 MB);
  0xa0000-0xdffff (VGA, option ROMs) goes to the board.
- BIOS ROM read once over the bus (`-r`, default 256 KB) into read-only
  memslots at the top of 4 GB and (its last 128 KB) at 0xe0000: KVM cannot
  execute from MMIO; ROM writes exit to the bus.
- I/O and MMIO exits: split into aligned 1/2/4-byte bus cycles.
- INTR polled at every exit, injected with the INTA cycle's vector once the
  guest takes interrupts (no in-kernel irqchip); HLT waits for INTR (HLT
  with IF = 0 is an error).
- CPUID: max leaf 2, signature `-s` (default 0x683, P-III cB0), features
  masked to a P-III (no APIC).
- Backends: `sim` (test devices, `bus_sim.c`), `fpga` (BAR0 through a
  sysfs PCI resource file; write cycles posted, a bus error reported at the
  next status read).

## BAR0 protocol (bus.h)

One 64-bit posted write per cycle, the command in the offset, so a bus
write costs one PCIe TLP and a read one TLP + one read completion (the
FPGA delays the completion until the bus cycle ends). STATUS carries INTR
and a sticky bus error; INTA runs the acknowledge cycle.

## Shadow RAM (`shadow.c`)

440BX PAM0-PAM6 (config 0:0:0 0x59-0x5f, datasheet 290633-001 sec.
3.3.17 Tables 3-2/3-3), tracked from the guest's 0xcf8/0xcfc writes (also
forwarded to the board): per segment (16 KB 0xc0000-0xeffff, 64 KB
0xf0000) a memslot over the shadow RAM if RE (read-only without WE), over
the ROM copy for RE = 0 at 0xe0000 and up (code keeps running from it),
none below; an exiting write lands in the shadow RAM if WE, else on the
bus. Tested: the BIOS copying its own segment while running from it,
read-only / read-write behaviour, an option-ROM segment. The VIA
VT82C694X uses other registers: a second map when that board comes.

## Viability (no hardware yet; operator 2026-11-02: design first)

Measured on this host (Ryzen 9 7950X3D, KVM, `c2-vmm` sim backend): a
guest I/O exit to the VMM and back 4.7 us, an MMIO exit 5.8 us; a `rep
insw` of 256 words is one exit (256,000 words in 0.05 s). The N100 is
slower per core (*estimate* 1.5-2x per exit) and a bus read adds the PCIe
round trip (*estimate* ~1 us, Gen2, plus the board bus cycle), so a board
access costs ~8-12 us, i.e. ~100K accesses/s; a P-III does a PCI I/O read
in ~0.3 us, an ISA one in ~1 us.

| load | access pattern | verdict |
|---|---|---|
| CPU + RAM (BIOS code after shadowing, DOS, Windows, Linux) | none | native N100 speed: the C2 goal |
| PIC / PIT / keyboard / CMOS / serial | a few per interrupt | fine (1-2 kHz timers: ~1-2 % of a core) |
| IDE PIO | `rep insw/outsw`, one exit per sector | fine if the bridge runs a repeated I/O cycle in one request (to add: count + FIFO window) |
| IDE / PCI bus-master DMA | snoops on the board bus | DMA mirror into guest RAM by PCIe bus mastering (VFIO / IOMMU), snoop stalls ~1-2 us per line: board tolerance to test |
| VGA text, BIOS video calls | few writes | fine |
| framebuffer graphics (mode 13h, VESA LFB) | one exit per write, ~100K/s | too slow trapped (a 64 KB frame ~0.2-0.6 s); needs the framebuffer as guest RAM with KVM dirty logging, the VMM copying dirty pages to the card in bursts (~60 Hz) |
| planar VGA (mode 12h, Mode X), 2D-accelerated drivers | reads of card state / VRAM written by the card | stay trapped (slow) or use a non-accelerated driver |

Verdict so far: viable for BIOS, DOS text programs, and Windows / Linux
desktop work with a VESA or LFB display, at ~10x a P-III in CPU work;
graphics-heavy DOS games and accelerated video drivers are the weak spot.
Risks only hardware can close: the real PCIe read latency of the N100 to
the FPGA, the board's tolerance of long snoop stalls (440BX; VIA snoop
filtering), AGP cards.

## Cable link v0 (card <-> cartridge, D32)

- Lines: 18 at 3.3 V LVCMOS on the cartridge (the 17 freed 3.3 V balls
  A[35:32]#, DEP[7:0]#, AP[1:0]#, AERR#, BERR#, BINIT# + free M8 = CLK0n,
  a clock input); RP#/RSP# and the free K19/K20 are 1.35 V (bank 7A),
  below a 3.3 V receiver's VIH, so they stay off the link.
- Cartridge header J5: 2 x 20, 2.54 mm, pin order of the ALINX 40-pin
  expansion header (AX7035B manual sec. 17, J9/J10: 1 GND, 2 +5 V, 3-36
  I/O behind 33 ohm, 37-38 GND, 39-40 +3.3 V): the 18 signals on odd pins
  3-35, even pins 4-36 GND on the cartridge (the card drives those I/O
  low: returns next to every signal wire), 1/37/38 GND, 2/39/40 not
  connected (no supply crosses the cable). A card with another header
  order (Puzhi: "40P x 2 ports, 62 single-ended", order unpublished) needs
  its manual checked first: a mismatch would short a signal to a card
  supply.
- Card candidates (nothing bought, operator 2026-11-02; the bridge needs
  little logic, an XC7A35T is plenty and in free Vivado): ALINX AX7A035B
  (XC7A35T, PCIe 2.0, 2 x 40-pin ALINX headers, public manual; ~302 EUR
  ex VAT at botland.store) or Puzhi PZ-A735T-KFB (the PZ-A7200T-KFB board
  with an XC7A35T, ~240-280 USD: Alibaba sample, Puzhi eBay store 279.99;
  header order unpublished). Buy from AliExpress or Alibaba.
- Down (card -> cartridge): clock (to M8) + 8 data; up: clock + 8 data.
  Bytes framed in-band (idle 0x00, a frame header byte with type and
  length); 50 MHz SDR first: 50 MB/s each way (DDR later if the cable
  allows).
- Budget per access: request 9 bytes (type, address, data) 180 ns down,
  reply 5 bytes 100 ns up, + the P6 cycle on the board (~150 ns at 66 MHz,
  ~1 us when the chipset forwards to ISA): small next to the ~5-10 us
  KVM exit; framebuffer lines (32 bytes + 5) ~43 MB/s: 640x480x8 at 60 Hz
  (18 MB/s) whole frames, larger modes dirty regions only.
- DMA mirror: a board DMA write (device -> memory) is recorded and its
  line copied up (board DRAM read on the bus, 37 bytes up, PCIe write into
  guest RAM): ~40 MB/s; a board DMA read (memory -> device) stalls the
  snoop while the line comes from guest RAM (request up, PCIe read ~1 us,
  33 bytes down): ~2 us per line, ~16 MB/s, so a disk write by DMA is
  ~half of UDMA/33.

## Next

0. Cartridge PCB (D32): S6 netlist (TA_ nets, 17 0-ohm RL01-RL17, J5),
   S7 placement, S8 re-route; J5 pin order once the card header pinout
   is known.
1. Bridge protocol: burst write (framebuffer pages) in bus.h; VMM
   framebuffer mirror (dirty logging). Done: string I/O as one REP
   command through a 4 KB BAR window (a sector: ~64 8-byte window reads
   instead of 256 read round trips; DMA into host memory later).
2. FPGA bridge v0 on the Puzhi board: PCIe 7 Series IP (x2 Gen2) + BAR0
   block + a loopback bus target (scratch RAM, POST port), then measure
   the N100 round trip per cycle (goal < 2-3 us, D28).
3. P6 bus agent: request/response phases, snoop stall (HIT# + HITM#), DMA
   mirror (slot1_variants common facts), A20M#, INIT#, SMI#, STPCLK#.
4. VMM: MSI through VFIO instead of polling, SMM, microcode-update MSRs.
