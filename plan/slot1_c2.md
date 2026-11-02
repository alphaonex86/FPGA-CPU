# Slot 1 C2: N100 + FPGA PCIe <-> P6 bridge, implementation

Variant C2 of `slot1_variants.md` (decided best, D26/D29): an Intel N100
runs Linux + KVM; one vCPU executes the board's stock BIOS and OS; every
guest access outside its RAM is a bus cycle on the Slot 1 board, run by an
FPGA that is a PCIe endpoint and a P6 bus agent. Test boards per slot1 D8
(440BX first). Bench hardware (D29): LattePanda Mu (N100) + Puzhi
PZ-A7200T-KFB (XC7A200T, PCIe 2.0 x2, Vivado verified).

## Parts

| part | where | status |
|---|---|---|
| VMM (KVM, one vCPU, bus backends) | `sw/c2-vmm/` | v0 done: real-mode test ROM passes on the sim backend |
| BAR0 bus protocol | `sw/c2-vmm/bus.h` | v0 defined |
| FPGA bridge: PCIe endpoint + BAR0 block | `rtl/c2/` (Puzhi, Vivado) | to do |
| P6 bus agent (AGTL+ cycles, snoop stall, DMA mirror) | cartridge FPGA or the bridge over a link | to do |
| Bench: N100 <-> Puzhi PCIe round trip | hardware | waits for the boards |

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

## Next

1. VMM: shadow RAM. The 440BX PAM registers (device 0:0 config 0x59-0x5f,
   seen as 0xcf8/0xcfc writes) select ROM or RAM per 16 KB of
   0xc0000-0xfffff: remap the memslots (RAM copy, read-only ROM, or bus).
   Option ROMs (VGA BIOS at 0xc0000) are fetched into a memslot when the
   BIOS shadows them.
2. FPGA bridge v0 on the Puzhi board: PCIe 7 Series IP (x2 Gen2) + BAR0
   block + a loopback bus target (scratch RAM, POST port), then measure
   the N100 round trip per cycle (goal < 2-3 us, D28).
3. P6 bus agent: request/response phases, snoop stall (HIT# + HITM#), DMA
   mirror (slot1_variants common facts), A20M#, INIT#, SMI#, STPCLK#.
4. VMM: MSI through VFIO instead of polling, SMM, microcode-update MSRs.
