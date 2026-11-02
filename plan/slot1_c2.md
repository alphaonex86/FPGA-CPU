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
| VMM (KVM, one vCPU, bus backends) | `sw/c2-vmm/` | v0 + 440BX shadow RAM + coalesced writes + 100 us tick: test ROM passes on the sim and rtl backends |
| BAR0 bus protocol | `sw/c2-vmm/bus.h` | v0 defined |
| PCIe card: BAR0 block -> cable link | `rtl/c2/c2_card.sv` | v0, simulated end to end (`test_rtl.sh`) |
| PCIe card: 7 Series PCIe IP wrapper (TLP <-> BAR0 request port) | `rtl/c2/xilinx/` | bitstream builds, timing met; LOOPBACK variant for bring-up |
| Cable link protocol (card <-> cartridge) | `rtl/c2/`; 22 cartridge balls (D32: 17 at 3.3 V, 2 at 1.35 V, 3 free) | v0 simulated through 3 clock domains; card I/O cells in the AX7A035B bitstream; cartridge I/O cells to do |
| Cartridge: link -> command executor on a generic bus port | `rtl/c2/c2_cart.sv` | v0, simulated |
| Cartridge PCB: link header J5 + 17 selection 0-ohms (D32) | `hw/slot1-cyclonev` generators | S6 netlist + S7 placement done; link nets unrouted like every slot net |
| Cartridge: link + P6 bus agent (AGTL+ cycles, snoop stall, DMA mirror) | `rtl/c2/c2_p6_agent.sv` | v0 (uncached cycles, agent 0) simulated against FPGAcommon's p6_bif; snoop / DMA mirror, CMOS pins, link CDC to do |
| Bench: host <-> PCIe card round trip | hardware | after the verdict |

## VMM v0 (`sw/c2-vmm`, `test.sh`)

- Guest RAM: 0-0x9ffff and 1 MB up (option `-m`, default 256 MB);
  0xa0000-0xdffff (VGA, option ROMs) goes to the board.
- BIOS ROM read once over the bus (`-r`, default 256 KB) into read-only
  memslots at the top of 4 GB and (its last 128 KB) at 0xe0000: KVM cannot
  execute from MMIO; ROM writes exit to the bus.
- I/O and MMIO exits: split into aligned 1/2/4-byte bus cycles (a dword
  at port 0xf6 is two word cycles, as the chipset splits it).
- INTR polled at every exit, injected with the INTA cycle's vector once the
  guest takes interrupts (no in-kernel irqchip); HLT waits for INTR (HLT
  with IF = 0 is an error). A 100 us SIGALRM tick forces an exit, so INTR
  also reaches a guest looping in RAM without I/O (a BIOS delay loop on the
  tick count; v0 without it hung there).
- Coalesced writes (KVM coalesced MMIO / PIO ring): the ATA data ports
  0x1f0/0x170 and the VGA window 0xa0000-0xbffff; every exit flushes the
  ring to the bus first, so the bus sees program order. KVM exits to
  user space once per element of a `rep outs` (`em_out`, count 1; only
  `rep ins` is batched, up to 1 KB) and once per MMIO write: coalescing
  keeps the exit in the kernel. Measured (7950X3D, sim backend): a VGA
  dword write 2.0 us coalesced vs 6.4 us trapped.
- KVM's private pages (VMX TSS, EPT identity map) sit just below the ROM
  window (the defaults fall inside a 512 KB+ ROM on Intel hosts).
- CPUID: max leaf 2, signature `-s` (default 0x683, P-III cB0), features
  masked to a P-III (no APIC).
- Backends: `sim` (test devices, `bus_sim.c`), `fpga` (BAR0 through a
  sysfs PCI resource file; write cycles posted, a bus error reported at the
  next status read), `rtl` (`test_rtl.sh` build: the same BAR0 protocol
  code on the Verilator model of card + link + cartridge, the cartridge's
  bus cycles served by the `sim` devices).

## BAR0 protocol (bus.h)

One 64-bit posted write per cycle, the command in the offset, so a bus
write costs one PCIe TLP and a read one TLP + one read completion (the
FPGA delays the completion until the bus cycle ends). STATUS carries INTR,
a sticky bus error and a sticky protocol error; INTA runs the acknowledge
cycle. The bridge takes requests strictly in order, one at a time (a
command holds later TLPs by flow control until its reply), so the REP
window is never refilled under a running REP.

## Bridge RTL v0 (`rtl/c2`, `sw/c2-vmm/test_rtl.sh`)

- `c2_card.sv`: BAR0 block on a vendor-neutral request port (req valid /
  ready, 64-bit writes, read response), 4 KB window (512 x 64), link out.
- `c2_cart.sv`: link in, one command at a time onto a generic board bus
  port (req / done, space, write, INTA, address, log2 size, data in the
  low bytes, error, INTR in), 4 KB REP buffer, reply.
- Link messages, one byte per clock, 0x00 between messages; one command
  in flight, every command answered:
  - down: CYCLE `{0x80 | space << 3 | write << 2 | log2 size, addr[4],
    data[4]}`; INTA `{0x40}`; REP `{0x20 | write << 2 | log2 size,
    port[2], count[2]}` + a write's data.
  - up: reply `{0x80}` + payload (read: 4 bytes, INTA: 1, REP read:
    count x size); status `{0x40 | error << 1 | INTR}` on an INTR change or
    a failed cycle, always before the reply.
- REP data is buffered whole on the receiving side (a 4 KB REP costs
  ~80 us of link time next to ~600 us of PCI I/O cycles).
- Tested: the whole test ROM through the RTL (2.7 M bridge clocks, link
  delay 3 clocks each way, bus cycles 8 clocks); a byte-lane mutation of
  the cartridge reply fails step 11.
- `xilinx/c2_tlp.sv`: 7 Series PCIe AXI4-Stream TLP engine (MWr 2 DW,
  MRd 1-2 DW on BAR0, UR otherwise); `c2_req_sync.sv` (PCIe user clock to
  link clock, toggle handshake), `c2_afifo.sv` (up link on the returned
  clock). `test_rtl.sh` drives real TLPs through all three clocks.
- Not yet: a link check (CRC).

## Card bitstream (`rtl/c2/xilinx`, AX7A035B)

- `build.tcl <out> [rom.hex]`: PCIe IP (`pcie_ip.tcl`: x2 Gen2, 8 KB
  BAR0, PIPE clock inside the core), synthesis, place and route, timing
  check, `c2_card.bit` + `c2_card_flash.bin` (SPI x4, compressed: ~24 ms
  to load, inside PCIe's 100 ms). Stops if a block was trimmed or timing
  fails. 2026-11-02: 1025 LUTs, 1834 FFs, 9 BRAM tiles, WNS 0.70 ns.
- With a ROM: LOOPBACK variant, `c2_cart` + `c2_loop_target` (the
  `bus_sim` devices in RTL, same test ROM) inside the card, serial out on
  the USB UART (L15, 115200 8N1): the whole PCIe + bridge path without
  the cartridge (4320 LUTs, 6372 FFs, 26 BRAM tiles, WNS 0.71 ns).
- `program.tcl <out>`: flash over JTAG (verify), boot from it.
- PERST# is not on an FPGA pin in the manual: reset from power-up and
  the RESET key; check the schematic on delivery.
- Bring-up on arrival (N100 host, root for the sysfs resource):
  1. `sw/c2-vmm/test_rtl.sh` (makes `build/rtl/test_rom.hex`), then
     `rtl/tools/vivado.sh rtl/c2/xilinx/build.tcl <out>
     sw/c2-vmm/build/rtl/test_rom.hex`, `program.tcl <out>`; reboot.
  2. `lspci -d 10ee:7022 -vv`: x2 5 GT/s, BAR0 8 KB; LED 1 (link up)
     and LED 3 (card idle) on; `echo 1 > .../enable`.
  3. `c2-probe fpga /sys/bus/pci/devices/<bdf>/resource0`: STATUS read
     (PCIe round trip), bus write / read cycle, REP MB/s (goal: cycle
     < 2-3 us, D28).
  4. `c2-vmm -e 0xf4 fpga /sys/bus/pci/devices/<bdf>/resource0`: the
     test ROM on the loopback devices, exit 0; its serial on the UART.
  5. Then the plain bitstream (no ROM) with the cartridge on J11.

## P6 bus agent v0 (`rtl/c2/c2_p6_agent.sv`)

- One c2_cart bus cycle = one P6 transaction, one at a time, as symmetric
  agent 0: Memory Data Read (00110), Memory Write may be retried (00111),
  I/O Read / Write (1000x), Interrupt Acknowledge (01000, LEN 00); UC
  ATTR, partial (LEN 00, BE from address and size); Retry re-issues,
  Hard Failure or any other answer is a bus error [HWDM Table A-7].
- Arbitration [PPRO1 4.1]: BREQ0# from 5 clocks after RESET#, then parked;
  BPRI# observed stops new requests; the BNR# stall / throttle / free
  sampling; at most one ADS# per 3 clocks; the in-order queue is tracked so
  RS#/TRDY# of earlier (chipset) transactions are not taken as ours.
- Inputs registered once: driven in T, observed in T+1, answered in T+2,
  the timing the [PPRO1] figures use (also the IOB flops of the real pins).
- `test_rtl.sh` runs the whole test ROM through it with FPGAcommon's
  `p6_bif` (copied to `rtl/tests/c2/`, the FPGAmotherboard chipset
  front end, whose protocol checks stop the run) as the chipset; two
  mutations (write data lane, write request code) fail the run.
- Straps A[12:5]# and RESET# are outputs for the bridge; not yet sent to
  the VMM (a link status bit for the board reset is next).
- `c2_bus_sync` crosses the bus port from the link clock to BCLK (toggle
  handshake each way, the request fields held by the cartridge); the sim
  runs BCLK at 14 ns against the 20 ns link clock.
- Not yet: HIT# / HITM# snoop stall and the DMA mirror, the CMOS pins (INTR via LINT0,
  NMI, INIT#, SMI#, A20M#, STPCLK# with its Stop Grant special cycle).

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
| IDE PIO read | `rep insw`: one exit per sector (KVM batches up to 1 KB), one REP command | fine |
| IDE PIO write | `rep outsw`: KVM exits once per word; coalesced (kernel exit only, ~2 us) and flushed as posted cycles | ~0.5 ms per sector, ~1 MB/s: slow but usable; DMA mode avoids it |
| IDE / PCI bus-master DMA | snoops on the board bus | DMA mirror into guest RAM by PCIe bus mastering (VFIO / IOMMU), snoop stalls ~1-2 us per line: board tolerance to test |
| VGA text, BIOS video calls | few writes | fine |
| VGA window graphics (mode 13h, planar 12h / Mode X) | writes coalesced (~2 us each measured + ~0.4 us bridge), reads exit | a 320x200 frame of dword writes ~40 ms (~25 fps), byte writes ~4x slower: DOS games playable at low frame rates |
| VESA LFB (PCI BAR above RAM) | trapped per write today | to do: the LFB as guest RAM with KVM dirty logging, dirty pages copied to the card by burst writes (~60 Hz); or coalesced like the VGA window once its BAR address is tracked |
| 2D-accelerated drivers | reads of card state / VRAM written by the card | stay trapped (slow) or use a non-accelerated driver |
| guest loops in RAM waiting for a timer tick | no exits | the 100 us tick injects INTR (~1-2 % of a core at 10 kHz) |

Verdict so far: viable for BIOS, DOS text programs, and Windows / Linux
desktop work with a VESA or LFB display, at ~10x a P-III in CPU work;
VGA-window DOS graphics run at low frame rates, accelerated video drivers
and PIO disk writes are the weak spots.
Risks only hardware can close: the real PCIe read latency of the N100 to
the FPGA, the board's tolerance of long snoop stalls (440BX; VIA snoop
filtering), AGP cards.

## Cable link v0 (card <-> cartridge, D32)

- Lines: 18 at 3.3 V LVCMOS on the cartridge (the 17 freed 3.3 V balls
  A[35:32]#, DEP[7:0]#, AP[1:0]#, AERR#, BERR#, BINIT# + free M8 = CLK0n,
  a clock input); RP#/RSP# and the free K19/K20 are 1.35 V (bank 7A),
  below a 3.3 V receiver's VIH, so they stay off the link.
- Cartridge header J5: 2 x 20, 1.27 mm SMD (a 2.54 mm one fits nowhere on
  the cartridge; D32 amendment in plan/slot1.md), pin order of the ALINX 40-pin
  expansion header (AX7A035B manual REV 1.1 sec. 3.11, J11: 1 GND, 2 +5 V,
  3-36 I/O behind 33 ohm in bank 16, 37-38 GND, 39-40 +3.3 V; table in
  `FPGAlist/c2_cards/README.md`): the 18 signals on odd pins 3-35 + pin 36,
  the up clock on 19 (card MRCC input), even pins 4-34 GND on the
  cartridge (the card bitstream drives those I/O low: a return next to
  every signal wire), 1/37/38 GND, 2/39/40 not connected (no supply
  crosses the cable). A card with another header order needs its manual
  checked first: a mismatch would short a signal to a card supply.
  Cable: a 1.27 mm 40-wire IDC ribbon (pin n to pin n) from J5 to a
  1.27 -> 2.54 mm 2 x 20 adapter plugged on J11.
- Card (decided by the operator 2026-11-02: AX7A035B, one order ~2026-11-16,
  arrival ~2026-12-16): ALINX AX7A035B (XC7A35T-2FGG484I, PCIe 2.0 x2,
  one usable 40-pin header J11, public manual; ~211-299 USD), chosen
  over Puzhi PZ-A735T-KFB (239 USD Alibaba, header order only in the
  docs sent after purchase). Details and seller questions:
  `FPGAlist/c2_cards/README.md`.
- Down (card -> cartridge): clock (to M8) + 8 data; up: clock + 8 data.
  J5 / J11 pin functions (straight ribbon, same numbers both ends; card
  side in `rtl/c2/xilinx/ax7a035b.xdc`): 3, 5, ..., 17 down data 0-7;
  19 up clock (card MRCC C18); 21 down clock (cartridge M8 = CLK0n);
  23, 25, ..., 35 and 36 up data 0-7; even 4-34 ground; 1/37/38 ground,
  2/39/40 open. Each side launches on its clock's rising edge and sends
  that clock inverted (DDR output), so the receiver samples mid-bit.
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

0. Cartridge PCB (D32): done S6 netlist (TA_ nets, RL01-RL17, J5,
   LINK_DCLK on M8) and S7 placement; the link nets get tracks with the
   other slot nets (S8c phase 2).
1. Bridge protocol: burst write (framebuffer pages, coalesced runs) in
   bus.h; VMM LFB mirror (dirty logging). Done: string I/O as one REP
   command through a 4 KB BAR window; coalesced ATA data / VGA writes.
2. AX7A035B on arrival (~2026-12-16): bring-up steps of "Card
   bitstream"; done before it: IP, top, J11 I/O, builds, flash script,
   c2-probe.
3. P6 bus agent: request/response phases, snoop stall (HIT# + HITM#), DMA
   mirror (slot1_variants common facts), A20M#, INIT#, SMI#, STPCLK#.
4. VMM: MSI through VFIO instead of polling, SMM, microcode-update MSRs.
