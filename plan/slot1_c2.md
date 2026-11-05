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
Since D40 (operator 2026-11-02): no external PC, ever; the x86 is a
LattePanda Mu on the cartridge ("Mu cartridge").

## Parts

| part | where | status |
|---|---|---|
| VMM (KVM, one vCPU, bus backends) | `sw/c2-vmm/` | v0 + 440BX shadow RAM + coalesced writes + 100 us tick: test ROM passes on the sim and rtl backends |
| BAR0 bus protocol | `sw/c2-vmm/bus.h` | v0 defined |
| PCIe card: BAR0 block -> cable link | `rtl/c2/c2_card.sv` | v0, simulated end to end (`test_rtl.sh`) |
| PCIe card: 7 Series PCIe IP wrapper (TLP <-> BAR0 request port) | `rtl/c2/xilinx/` | bitstream builds, timing met; LOOPBACK variant for bring-up |
| Cable link protocol (card <-> cartridge) | `rtl/c2/`; 22 cartridge balls (D32: 17 at 3.3 V, 2 at 1.35 V, 3 free) | v0 simulated through 3 clock domains, link reset; I/O cells in both bitstreams |
| Cartridge: link -> command executor on a generic bus port | `rtl/c2/c2_cart.sv` | v0, simulated |
| Cartridge PCB: link header J5 + 17 selection 0-ohms (D32) | `hw/slot1-cyclonev` generators | S6 netlist + S7 placement done; link nets unrouted like every slot net |
| Cartridge: link + P6 bus agent (AGTL+ cycles, snoop stall, DMA mirror) | `rtl/c2/c2_p6_agent.sv` | v0 (uncached cycles, agent 0, CMOS pins, Special Transactions) simulated against FPGAcommon's p6_bif; snoop / DMA mirror to do |
| Cartridge bitstream (variant A PCB, 5CEFA9) | `rtl/c2/cyclonev/` | builds, timing met at BCLK 66 MHz with the P6 pin timing constrained |
| Dedicated C2 cartridge PCB; C2 cartridge with its own PCIe (Cyclone V GX) | `hw/` | decided 2026-11-02 (D33, D34), to design |
| Bench: host <-> PCIe card round trip | hardware | after the verdict |

## VMM v0 (`sw/c2-vmm`, `test.sh`)

- Guest RAM: 0-0x9ffff and 1 MB up (option `-m`, default 256 MB);
  0xa0000-0xdffff (VGA, option ROMs) goes to the board.
- BIOS ROM read over the bus at each board reset (`-r`, default 256 KB;
  it may have been flashed) into read-only memslots at the top of 4 GB and (its last 128 KB) at 0xe0000: KVM cannot
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
- Board reset (RESET#; also awaited at start): the VMM waits for its end,
  reads the ROM again, sets PAM0-6 to 0, restores the vCPU's power-on
  state (EDX = signature, reset vector FFFFFFF0h or 000FFFF0h with the A6#
  strap) and drops coalesced writes not yet on the bus; guest RAM is kept,
  like DRAM. The test ROM ends with a 0xcf9 hard reset and checks EDX,
  PAM and its RAM marker after it (mutations fail steps 14 and 15).
- CPU pins (status bits; edges kept until handled): INIT# restarts the
  vCPU like a reset but keeps PAM and the x87 state; NMI via KVM_NMI;
  A20M# maps 0x100000-0x10ffff onto 0-0xffff (memslot 3: all real mode
  reaches; A20M# in protected mode is undefined); STPCLK# stops the vCPU
  after a Stop Grant Acknowledge until negated; SMI# is counted and
  ignored (no SMM yet). HLT sends a Halt Transaction (the chipset wants
  every one) and waits; HLT with IF = 0 waits for an event. A triple fault
  sends Shutdown and waits for INIT# / RESET# (PIIX4: INIT#), then opens a
  new KVM VM over the same memory: on this AMD host KVM reinitialises the
  VMCB at a shutdown and the vCPU then makes no progress (seen in this
  session, KVM 7.1.8). Test ROM steps 16-21: NMI, STPCLK#, Halt count,
  A20M# wrap both ways, port 0x92 INIT# (PAM kept), triple fault; the
  mutations (no KVM_NMI, no Halt, no A20 alias, INIT as a reset) fail
  their steps.
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
a sticky bus error, a sticky protocol error, the board reset (RESET#
asserted or since the last read; bus cycles under it fail and are not
errors), the A6# strap, A20M# / STPCLK# and sticky NMI / INIT# / SMI#
edges; INTA runs the acknowledge cycle, SPECIAL a Special Transaction,
LINK_RESET (0x028) resynchronizes the link (the VMM issues it at open).
The bridge takes requests strictly in order, one at a time (a
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
    data[4]}`; INTA `{0x40}`; SPECIAL `{0x48 | sub-code}`; REP `{0x20 |
    write << 2 | log2 size, port[2], count[2]}` + a write's data.
  - up: reply `{0x80}` + payload (read: 4 bytes, INTA: 1, REP read:
    count x size); status `{0x40 | A6# << 3 | board reset << 2 | error <<
    1 | INTR}` on a level change or a failed cycle, always before the
    reply; between commands pins `{0x50 | STPCLK# << 1 | A20M#}` on a
    change and events `{0x60 | SMI# << 2 | INIT# << 1 | NMI}` on an
    assertion edge; both level messages every 2^16 clocks (a card reset
    relearns the levels; until then the card reports the board in reset).
- REP data is buffered whole on the receiving side (a 4 KB REP costs
  ~80 us of link time next to ~600 us of PCI I/O cycles).
- Tested: the whole test ROM through the RTL (2.7 M bridge clocks, link
  delay 3 clocks each way, bus cycles 8 clocks); a byte-lane mutation of
  the cartridge reply fails step 11.
- `xilinx/c2_tlp.sv`: 7 Series PCIe AXI4-Stream TLP engine (MWr 2 DW,
  MRd 1-2 DW on BAR0, UR otherwise); `c2_req_sync.sv` (PCIe user clock to
  link clock, toggle handshake), `c2_afifo.sv` (up link on the returned
  clock). `test_rtl.sh` drives real TLPs through all three clocks.
- Link reset (the card's reset, or LINK_RESET at VMM open): a command left
  half sent (card reset) or a reply still due (card timeout) would desync
  the link. The card stops the down clock for 2^10 clocks (~20 us) and
  holds BAR0; `c2_bus_sync` sees no link clock edge for 64 BCLKs and sets
  the cartridge's link_lost at once (asynchronous set, the clock may be
  stopped); c2_cart lets a running bus cycle end, drops the command and
  its reply, reports flushed, and sends its levels 16 clocks after the
  loss clears; the card drops the first 8 up bytes after the quiet (stale
  pipeline bytes), clears its sticky errors and events and shows the
  board in reset until that status. `test_rtl.sh` injects half a command
  with the cartridge clock stopped, a bad up byte and stale bytes after
  every quiet; mutations (no link reset, no flush, no watchdog, no drain,
  no sticky clear) each fail a backend.
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
- RESET# and the A6# strap (reset vector) cross to the link clock in
  `c2_bus_sync` and reach the VMM in the status message; a request under
  RESET# ends in a bus error at once. The other straps (IOQ depth, BINIT#,
  cluster ID) need nothing from the agent: one transaction at a time.
- Special Transactions (REQa 01000, REQb[0]#, sub-code on BE[7:0]#, No
  Data expected): Halt, Shutdown, Stop Grant Acknowledge from the VMM;
  p6_bif's spc_stb reaches the sim devices.
- CMOS inputs A20M#, STPCLK#, NMI, INIT#, SMI# cross in `c2_bus_sync`
  (2 flops; the edge pins stretched 7 BCLKs first, as INIT# / SMI# may be
  2 BCLKs = 15 ns at 133 MHz, shorter than a link clock). Sim devices and
  `c2_loop_target` model the PIIX4 port 0x92 (FAST_A20, FAST_INIT), the
  Shutdown -> INIT# rule and a test port 0xf8 (NMI, STPCLK#, Halt / Stop
  Grant counts).
- `c2_bus_sync` crosses the bus port from the link clock to BCLK (toggle
  handshake each way, the request fields held by the cartridge); the sim
  runs BCLK at 14 ns against the 20 ns link clock.
- Not yet: HIT# / HITM# snoop stall and the DMA mirror; SMM (SMI
  Acknowledge, SMMEM#, 440BX SMRAM); IGNNE# / FERR# (KVM has no FERR#);
  FLUSH#.

## Cartridge bitstream (`rtl/c2/cyclonev`, variant A PCB)

- `build.sh <a|c2cart> <out_dir>`: `c2_cart_core.sv` (everything but the
  pins) under `c2_cart_top.sv` (variant A) or `c2_cart_gtl_top.sv`
  (dedicated PCB, below).
- `c2_cart_top.sv`: c2_cart on the received link clock (M8), c2_bus_sync,
  c2_p6_agent on BCLK through `c2_bclk_pll` (normal mode: the raw pin ->
  I/O register clock path is ~5 ns, which would capture the chipset's data
  of the same edge); open-drain pins; `gen_qsf.py` makes the QSF from
  `hw/slot1-cyclonev/pins.csv` and the J5 table (every net a port or
  listed unused); `build.sh` fails on any critical warning, an unplaced,
  ignored, unpackable or incomplete pin assignment, a latch or timing.
- Every P6 flop sits in an I/O cell (inputs, open-drain outputs; the
  agent is synthesized without synchronous controls so they pack). The
  P6 pins are constrained to the Pentium II edge-finger timing [p2 Table
  12: valid 0.71-4.66 ns, setup 1.97, hold 1.61, for its 100 MHz bus;
  the chipset's own timing does not scale with the period] through the
  pass-gate (0-0.3 ns) and the cartridge traces (0.1-0.3 ns).
- BCLK 66 MHz (D27): at 100 / 133 MHz the one-clock reactions cross the
  die (control pins on both edges, NM46). 2026-11-02: 513 ALMs, 684
  registers; slack: P6 outputs +0.58 ns, core +0.82, link +6.7.
- AGTL+ drive: 3.3-V LVTTL 16 mA, SSTL-135 series 34 ohm (no RZQ); the
  1.35 V outputs cannot pull a double-terminated line below VIL (NM45):
  a driving GTL+ buffer on the outputs (D35).
- The board must run 66 MHz: 100/66# low on the cartridge (a tie on the
  next PCB revision) or the board's FSB jumper.

## Dedicated cartridge PCB (D33) with GTL+ transceivers (D35, D37)

`hw/slot1-c2cart/` (`pins.csv` from `hw/tools/gen_c2cart_assign.py`),
independent of the variant A routing; bitstream `build.sh c2cart`
(`c2_cart_gtl_top.sv` + `.sdc`).

- FPGA 5CEBA4F23C8 (or A2; an A9 drops in): pins only on the 208 F484 IO
  balls that are IO on both A4 and A9 (16 bank-7A balls are A9-only, 16
  A4-only); the board powers the A4's VCCIO2A/VCCPD1A2A balls (NC on the
  A9). Banks 3.3 V except 3A: RX at SSTL-18 (VCCIO3A 1.8 V, VCCPD3A
  2.5 V). No DDR3.
- AGTL+ drive and the wide groups through 7 x SN74GTL16612DGG (18-bit
  LVTTL <-> GTL+ transceiver, B port 40 mA at VOL 0.4 V = ~0.4 V into the
  double-terminated 28 ohm line vs VIL 0.82 V) [ti_sn74gtl16612]; every
  chip's CLKAB = CLKBA from its own output of a CY2309 zero-delay buffer
  (REF = BCLK), CEAB#/CEBA# low, LEAB from the FPGA pin AB_LE (high: A -> B
  transparent, low: clocked; the bitstream picks):
  | group | chips | lines | B -> A |
  |---|---|---|---|
  | ADDR | 2 | A[31:3]#, REQ[4:0]# | transparent (LEBA high; only the straps are read), FPGA OEAB#/OEBA# pair |
  | DATA | 4 | D[63:0]# | clocked (LEBA low), FPGA OEAB#/OEBA# pair |
  | TX | 1 | ADS#, DRDY#, DBSY#, BR0#, BNR#, HIT#, HITM# | off (OEBA# high); OEAB# from the FPGA; the lines C2 does not drive are driven high (released) |
  Spare channels: both sides open. Direction change, contention-free on
  the LVTTL side: OEBA# off and the FPGA drives high (released) one BCLK
  before OEAB# on; OEAB# stays one BCLK after the last drive (a clocked
  A -> B shows the data one BCLK after its OEAB#; the open-drain B side
  is off meanwhile); dir falls one BCLK after OEAB#. ADDR goes out one
  BCLK before ADS# (the agent rechecks BPRI#/BNR# then); DATA goes out
  when our write heads the in-order queue and the data bus is quiet.
- **D37 receive path and transceiver clocks** (timing study 2026-11-02,
  Quartus 5CEBA4 C8 at 66 MHz, slow 85 C / fast 0 C):
  - Through the transparent 16612 (B -> A 1.1-6.3 ns) the inputs miss by
    ~0.7 ns in either PLL mode (normal, source synchronous). So the
    control lines the agent observes (ADS#, BNR#, BPRI#, TRDY#, DBSY#,
    DRDY#, RS[2:0]#, RESET#, DEFER#, LOCK#, HIT#, HITM#, BR0#) go
    straight from their contacts to bank 3A (SSTL-18 Class I, VREFB3AN0
    0.96 V = 1.00k/1.78k from VTT, inside the 0.833-0.969 V spec [cvds
    Table 16]; thresholds 0.835/1.085 V DC vs the bus's 0.82/1.22 V [p2
    Table 12]): setup/hold slack >= 1.1 ns. D# is registered in the DATA
    chips at BCLK and reaches the FPGA one BCLK later (`c2_p6_agent`
    D_CLOCKED: read data follows DRDY# by one clock; RTL test p6gtl
    models the register, a non-clocked agent hangs it): slack >= 1.8 ns.
  - CLKBA cannot come from the FPGA: its forwarded clock moved -2.0 to
    +5.7 ns across PVT against a 5.4 ns window. The CY2309 (REF at its
    VDD/2 threshold, +-0.35 ns, 0.25 ns skew, 0.2 ns jitter, +0.4 ns for
    the threshold: -0.8..+1.2 ns) meets B setup 2.3 / hold 0.3 (-4.4..
    +1.4 ns) and, through CLKAB -> B 1.9-5.5 ns, the P6 output window
    (0.71 ns hold, valid by t_spec - 4.66 ns before the next edge); the
    SDC computes these windows and fails the build if they break.
  - Outputs, transparent A -> B (1.3-4.1 ns): the FPGA's own tco spread
    (2.96-8.6 ns from its clock) leaves ~0 ns (-0.07..+0.06 ns over three
    fits, agent 3.4-3.6 ns before BCLK; 16 mA drive does not help).
  - Outputs, clocked A -> B (agent 1.75 ns after BCLK, inputs sampled
    5 ns before it): bus side setup +1.7 / hold +2.1 ns, OEAB# +0.66 ns,
    but the agent's
    input -> output paths get 6.75 ns and miss by up to 4.4 ns (TRDY#/
    DBSY# -> the 64 D# drives; BPRI#/ADS# -> the address and ADS#
    drives, RESET# -> the directions, D# -> the read data register).
    Next: a write wait state ([PPRO1] p.3-21: DBSY# held in the clock
    before a late DRDY#, so the 64 drives load from a register), the
    address loaded in PREP whatever `go` says (OEAB# keeps it off the
    bus), the read data one register later; then the default top
    (`c2_cart_gtl_top.sv`, AB_LE low) closes or the transparent mode
    gets the faster speed grade. `build.sh c2cart` fails timing until
    then; variant A builds.
- A[35:32]#, AP[1:0]#, DEP[7:0]#, RP#, AERR#, BERR#, BINIT#, IERR#,
  BP/BPM#: terminated, not connected (C2 uses no parity, 32-bit addresses).
- Every AGTL+ net keeps its 56 ohm processor-end termination to the slot
  VTT; 16612 VREF 1.0 V = 2/3 VTT divider, 0.1 uF at each 16612; the
  FPGA's 3A VREF its own divider. CMOS pins (2.5 V) through CB3T3245
  pass-gates.
- Power (variant A's tree minus DDR3): 12 V barrel (D13) -> PS1
  TPS54620 5 V (the 16612 VCC5: ICC5 120 mA max each, 0.84 A) -> PS2
  TPS54620 VCC 1.1 V; TPS62130 PS3 VCC_AUX 2.5 V (+ FPLL bead, VCCPD3A),
  PS4 VCCIO 3.3 V (3.3 V banks, their VCCPD, the 16612 VCC3.3, the
  CY2309, VCCPGM: AS x1 configuration from an EPCQ128A, MSEL 10011
  [cvhb Table 7-2], the AS pins on VCCPGM [cvhb 7-13]),
  PS5 VCCIO3A 1.8 V (input-only bank). 100/66# tied low (66 MHz).
  Pull-ups on the five FPGA OE# lines keep the ADDR/DATA/TX transceivers
  off while the FPGA configures (the 16612 bus-hold would keep an
  undriven A input low: a weak FPGA pull-up does not overdrive it).
- Schematic + netlist: `python3 hw/tools/gen_c2cart_s6.py` ->
  `hw/slot1-c2cart/slot1-c2cart.kicad_sch` / `.net` / `pdn.csv` (238
  passives + regulators): U1 FPGA, U2 contacts, U3-U9 16612, U10-U11
  CB3T3245 (VCC 2.5 V), U12 CY2309 (22 R per chip clock, CLKOUT 22 R +
  10 pF ~ one chip's CLKAB + CLKBA load), U13 EPCQ128A (SOIC-16W
  assumed: the datasheet gives no outline), J1 USB-Blaster 10-pin at
  VCCPD3A 2.5 V (JTAG pins in 3A [pcg-01014]), J3 12 V, J5 link; RN1-35
  56 R packs on the 137 AGTL+ contacts (RESET# excluded: board-terminated);
  RREF_TL 2.00k 1 % (PLLs used [pcg-01014]); VID 00001 by 0 R straps.
  Audit (every pins.csv net, chip clocks, AS, VREFs, terminations, supply
  bands) and ERC: 0 errors.
- Placement: `python3 hw/tools/gen_c2cart_s7.py` -> `slot1-c2cart.kicad_pcb`
  (variant A substrate, edge, keep-outs, power strip): F.Cu chip band
  y 7.1-21.6 in FPGA ball order (DATA0-3, CY2309, ADDR0-1, TX), U1 at
  (63.5, 34.3), J5 + CB3T3245s left, EPCQ + J1 right; B.Cu the RN row
  along the edge at its contacts' x, supply caps under each chip's pins,
  CY2309 series parts under it. 254 footprints, DRC 0. Next: routing
  (layer count: the 3A RX balls sit on U1's far side, 15 nets around
  or under it; a 1.0 mm F484 with ~160 signals wants >= 4 layers).
- Variant A also gets D35 later: its 1.35 V banks cannot take the 16612's
  3.3 V A-port outputs (receive-only nets there, NM45 option 1).

## C2 cartridge with its own PCIe (D34)

`hw/slot1-c2pcie/`. The D33 board (bus side, 16612s, CY2309,
CB3T3245s, EPCQ, power tree) with a Cyclone V GX instead of the E and an
OCuLink 4i receptacle (SFF-8612, 42 circuits) instead of the J5 link; the
N100 host plugs an OCuLink cable (or a slot / M.2 -> OCuLink adapter).
- FPGA: F484 GX, pins only on balls that are IO on every 5CGXFC4/C5/C7/C9
  and 5CGTFD9 (224 common IO, the same 3A..8A banks as the E; the six
  GXB channels L0-L5, REFCLK0L/1L and the GXB supplies sit on the same
  balls in all five) [FPGAlist/CycloneV_GX/pins]: the density (and GX
  Gen1 vs GT Gen2) stays a purchase choice.
- PCIe x4 on the bottom-left Hard IP: lanes 0-3 = GXB channels Ch0-Ch3
  (L0..L3), Ch4 = the transmit CMU PLL, Ch5 free [ug_c5_pcie_avst Figure
  4-38]; pin_perst = nPERSTL1 (R17, bank 5A) [same, pin_perst]; refclk on
  a dedicated REFCLK pin, 100 MHz from the cable (common clock).
- OCuLink endpoint side [SFF-9402 Rev 1.1 Table 6-1, SFF-8621 column]:
  A3/A4 PERp0/n0 ... A18/A19 PERp3/n3 (host -> us: GXB RX), B3/B4 PETp0/n0
  ... B18/B19 PETp3/n3 (us -> host: GXB TX, 0.1 uF series caps here),
  B12/B13 REFCLK+/-, A12 PERST#, A13 CPRSNT# (endpoint ties it low),
  A9/A10 2W-CLK/DATA, B9 BP_TYPE, B10 CWAKE#, A1/B21/B1/A21 power: no wire.
- Generated by the D33 tools with the board name `c2pcie`
  (gen_c2cart_assign/s6/s7.py): 157 nets (A[26]# moved to M21), audit OK,
  ERC 0; 275 footprints placed, DRC 0. GXB supplies from the 1.1 V / 2.5 V
  rails through BLM21PG221SN1D beads [pcg-01014 Example 1]; RREF 2.0k;
  L4/L5 RX and REFCLK1L to GND; PERST# 10k pull-down.
- J6 footprint from SFF-8612 Table 5-4 / Appendix A: its locating holes sit
  0.07 mm from pads A1/A21 by the spec, so `slot1-c2pcie.kicad_dru` relaxes
  hole clearance for J6 only. 3D body: the nearest stock right-angle
  receptacle (HDMI-A Amphenol), no SFF-8612 model in the stock set.
- Open: GXB bead current from the EPE; REFCLK0L reaching the Ch4 CMU and
  nPERSTL1 binding, to verify with a Quartus build of the PCIe HIP
  (gen_qsf/top for c2pcie); routing (layer count, 85 ohm diff pairs).

## Mu cartridge (D40)

`hw/slot1-c2mu/`: the D39 Artix cartridge with a LattePanda Mu on
a DDR4 SO-DIMM 260 socket on the board instead of the OCuLink; no
external PC (operator: never). Docs offline in
`sockets/slot1/lattepanda_mu/` (LattePandaTeam/LattePanda-Mu): edge
pinout xlsx, KiCad symbol + module footprints (H4.0 / H8.0 stacking),
dimension drawing, module STEP, Lite / Mini carrier schematics, BIOS notes.
- Module: N100 or N305 (preferred N305, 16 GB, 64 GB eMMC: BIOS
  S70NC1R200-16G-B), 60 x 69.6 mm, VIN 9-20 V on pins 251-259
  [edge_connector_pinout.xlsx].
- PCIe x4 to the FPGA: HSIO8-11 = PCIe 3.0 x4 lanes 0-3 by the default
  BIOS [bios_dflt_README.md HSIO]; on the Lite carrier the x4 slot takes
  REFCLK2 (pins 97/99) and ~PLT_RST (pin 105), the module's TX through
  series caps (netlist of the Lite carrier V2 KiCad project, nets
  /LattePanda Module/REFCLK2+-, /~PLT_RST, /PCIe x4/PCIE30_TX0_P). Here
  both directions sit on our board: 0.22 uF in each TX lane (Mu TX ->
  GTP RX, GTP TX -> Mu RX); REFCLK2 AC-coupled into MGTREFCLK1 (F10/E10);
  PLT_RST# into a 3.3 V FPGA IO as PERST#. The link trains at Gen2
  (GTP limit).
- Power: 12 V input (Mu VIN + the FPGA / 16612 rails); budget ~30 W
  (N305 > 15 W + 50 % margin, fan, FPGA; viability.md), allowed by the CLAUDE.md external-supply rule for
  the C2 gain.
- Viability (2026-11-04): `sockets/slot1/lattepanda_mu/viability.md`: viable; operator: ~75 mm PCB accepted, buy N305 16 GB + FIT0981 + Lite carrier (bring-up); the PCB grows to ~75 mm high (Mu courtyard 65.4 mm), LOTES 9.2H socket (LCSC), FPGA under the module.
- Flow (each step a script, PASS/FAIL): `gen_mu_lib.py` (Mu symbol from
  the vendor xlsx, LOTES 9.2H socket and M2 standoff footprints),
  `gen_c2mu_assign.py` (pins.csv: least-total-length matching of each
  net to its other end, so no two bus lines cross), `build_c2mu.tcl`
  (bitstream x4 Gen1, 2026-11-05: WNS +0.245 / WHS +0.052 ns, 1.0 W), `gen_c2mu_s6.py`
  (schematic, ERC 0), `_s7.py` (placement: FPGA and the transceiver band
  under the module, parts <= 4 mm there; connectors, PS1 coil and C1 in
  the free column; DRC 0), `_s8.py` (planes, via in every U1 ball, plane
  fanout, pre-route DRC 0, freerouting), `_s9.py` (DRC gate, JLC BOM with
  LCSC numbers and live stock, CPL, Gerbers).
- Mu power-on: SW1 + Q1 (FPGA MU_PWR_ON) on PWR_SW#, Q2 on RST_SW#; USB
  2.0 x2 header (J6) and UART header (J7) for installing the VMM on the
  eMMC; FT232H on Mu USB port 2 as the FPGA's JTAG (ADBUS0-3 = TCK, TDI,
  TDO, TMS: the MPSSE JTAG pins). Flash from the Mu itself:
  `openFPGALoader -c ft232 --fpga-part xc7a100tfgg484 -f c2mu.bit` (its
  SPI-over-JTAG bridge). W25Q128JVSIQ: QE fixed at 1 by the factory, so
  the SPI x4 boot needs no setup [winbond_w25q128jv 7.1.4].
- Parts (2026-11-04, JLCPCB stock for 2 boards: all but one): swapped to
  stocked equivalents W25Q128JVSIQ, SX2M 50 MHz, FXL1040-6R8, YC124 56R,
  TS-1187A, T520D 330 uF/6.3 V; standoffs Sinhoo SMTSO2066CTJ (M2, 6.6 mm,
  reflowed). SN74GTL16612DGGR: not at LCSC/JLCPCB; TI lists it ACTIVE and
  in stock (~US$5.9): JLCPCB Global Sourcing or consigned. Parts at JLCPCB
  list prices ~US$463 for 2 boards (2 x XC7A100T-2FGG484I ~US$66).
- Open: JLCPCB's placement preview (its rotations differ from KiCad's for
  some packages); GTL16612 purchase route.

## Artix cartridge (D39)

`hw/slot1-c2art/` (to do). The D34 board with an XC7A100T-2FGG484I in
place of the Cyclone V GX: 285 IO in banks 13 (35), 14, 15, 16, 34, 35
(50 each), VCCO per bank chosen on the PCB, 4 GTP (one quad) + 2 GTP
reference clock pairs [xilinx/xc7a100tfgg484pkg.txt]; the card RTL
(`rtl/c2/xilinx`, PCIe 7 Series IP) and the P6 agent in one FPGA.
- PCIe x4 Gen2 over the OCuLink 4i (D34 pinout), refclk from the cable
  on an MGTREFCLK pair, PERST# on an IO.
- Bought as one JLCPCB order (PCB + BGA assembly + parts from LCSC,
  PayPal). D40 replaces the OCuLink / external PC by a LattePanda Mu on
  the cartridge.
- PCIe lanes (Vivado 2025.2, pcie_7x x4 on xc7a100tfgg484-2: lane k on
  GTPE2_CHANNEL_X0Y(7-k), site -> pins by get_package_pins): lane 0 TX
  D7/C7 RX D9/C9, lane 1 B6/A6 B10/A10, lane 2 D5/C5 D11/C11, lane 3
  B4/A4 B8/A8 (MGTPTXP3..0_216); refclk MGTREFCLK1 F10/E10. The same
  lanes 0-1 as the AX7A035B. x4 Gen2 needs the 128-bit 125 MHz (or
  64-bit 250 MHz) interface: the board wires x4, the bitstream may stay
  x2 Gen2 (64-bit, current RTL) or x4 Gen1.
- Bank plan (ball centroids in the footprint orientation, ball 22 to the
  card edge): banks 14/15/16 face the edge, 13 the right middle, 34/35
  and GTP 216 the far side. Bank 15 at 1.8 V: the 15 RX lines straight
  from the contacts (SSTL18_I, INTERNAL_VREF 0.90: AGTL+ 0.6 V low /
  1.5 V high leave 0.2 / 0.5 V; no divider). Banks 14 (45 IO after the
  SPI x4 flash pins), 16 and 13 at 3.3 V: 111 bus nets (64 data,
  34 address, 7 tx, 6 control) + 11 CMOS + BCLK (MRCC, LVCMOS33: the
  2.5 V clock passes VIH 2.0 V) + PERST#. Banks 34/35 at 3.3 V too:
  the spare balls let every net sit at most 3 rings deep (all-top banks
  reached 9 rings: the 3 signal layers could not escape them, 2026-11-05).
  Bank 0 and CFGBVS at 3.3 V.
- Power: VCCINT + VCCBRAM 1.0 V, VCCAUX + VCCO15 1.8 V, MGTAVCC 1.0 V and
  MGTAVTT 1.2 V on their own regulators, VCCO 3.3 V; order VCCINT ->
  VCCAUX -> VCCO, MGTAVCC after VCCINT, MGTAVTT after MGTAVCC [UG482].
- To do: the c2art board in gen_c2cart_assign/s6/s7 (Xilinx tables,
  this bank plan, power tree, SPI flash, JTAG), timing of the P6 agent
  on the Artix -2.

## SoM cartridge (D38, replaced by D39)

`hw/slot1-c2som/` (not done). The AX7A035B core board AC7A035 (60 x 60 mm,
mounting holes on a 55 mm square, 5 V only on CON1 pins 1-8; XC7A35T-2,
1 GB DDR3, 128 Mb QSPI on the SoM) on a Slot 1 carrier with the D33 bus
side (16612s, CY2309, terminations) and the D34 OCuLink 4i; the PC gets
a PCIe x4 -> OCuLink adapter card. [AX7A035B manual sec. 2.9-2.11]
- SoM connectors: 4 x 80 pins, 0.5 mm, Panasonic P5K 3.0 mm mated
  height; SoM side AXK580137YG socket, carrier side AXK680337YG header
  (with positioning bosses, on-demand part); AXK680347YG is the stock
  header without bosses, same mating [panasonic_p5k_catalog.pdf p.4-6].
  Insertion life 50 cycles: move the SoM between the ALINX carrier and
  ours only a few times. Header land pattern [same, p.11]: 2 rows of 40,
  0.25 x 2.30 pads at 0.5 mm, rows 1.00 apart (5.60 overall), outermost
  pads 0.75 wide (0.125 inside to 0.625 outside the end pin centre).
- IO on the connectors: 145 at 3.3 V (bank 14: 45, banks 15/16: 50 + 50,
  VCCO from LDOs on the SoM), 15 at 1.5 V (bank 34, DDR3 bank), bank 13
  not bonded on the 35T; the 4 GTP channels + MGT_CLK1 (F10/E10) and
  JTAG (CON3 77-80). The C2 bus side needs 139 IO (64 data, 34 address,
  15 rx, 11 CMOS, 7 tx, 6 control, 1 clock) + PERST#: every AGTL+ line
  goes through a 16612 (no SSTL-18 bank on the SoM: the D37 direct
  receive becomes a 16612 path, timing to recheck on the Artix -2).
- PCIe x4 Gen2 on GTP 0-3 (the AX7A035B carrier wires only 2 + 2 to
  SFP); PERST# from OCuLink A12 onto a SoM IO.
- Open: the exact CON1-CON4 positions and pin-1 orientation on the SoM
  (the manual dimensions only the 55 mm hole square): ALINX core board
  footprint on request, or a 1200 dpi scan of the delivered board;
  board height (60 mm SoM + the 16612 band > the 57.8 mm D33 outline).

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

0. Cartridge PCBs: variant A (D32): done S6 netlist (TA_ nets, RL01-RL17,
   J5, LINK_DCLK on M8) and S7 placement; the link nets get tracks with
   the other slot nets (S8c phase 2). New (D33-D37): a dedicated C2
   cartridge (ball map, symbols, schematic + netlist, bitstream draft;
   timing open: "Dedicated cartridge PCB"), a C2 cartridge with its own PCIe, GTL+ output buffers.
1. Bridge protocol: burst write (framebuffer pages, coalesced runs) in
   bus.h; VMM LFB mirror (dirty logging). Done: string I/O as one REP
   command through a 4 KB BAR window; coalesced ATA data / VGA writes.
2. AX7A035B on arrival (~2026-12-16): bring-up steps of "Card
   bitstream"; done before it: IP, top, J11 I/O, builds, flash script,
   c2-probe.
3. P6 bus agent: snoop stall (HIT# + HITM#), DMA mirror (slot1_variants
   common facts), SMM. Done: transactions, RESET# / straps, CMOS pins,
   Special Transactions.
4. VMM: MSI through VFIO instead of polling, SMM, microcode-update MSRs.
