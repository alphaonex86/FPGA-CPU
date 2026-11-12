# Next steps: socket3-cyclonev and slot1-c2mu to fabrication (handoff 2026-11-11)

Goal (operator 2026-11-11): both boards routed, verified down to the FPGA build, fab files written
with every gate passing. Read AGENTS.md first; details in plan/interposers.md (T5, T8, T9 status
2026-11-11), plan/slot1_c2.md (Mu cartridge), plan/x86_core.md (M8).

## Running now (no action needed)

- `fpgacpu-route.service` (user service, survives a reboot): routes socket 3, then the C2 Mu.
  State: `python3 hw/tools/route_search.py --status hw/socket3-cyclonev/socket3-cyclonev.kicad_pcb
  hw/slot1-c2mu/slot1-c2mu.kicad_pcb`; log: `hw/<board>/route/search.log`; output: `hw/.route.out`.
  A complete board gets `gen_*_t8.py --finish` / `gen_c2mu_s8.py --finish`, then its fab step,
  by the service itself (`route/<script>.log`).
- `rtl/s3/build.sh rtl/build/s3` (Quartus, ~55 min) was started at handoff. A complete build
  leaves `rtl/build/s3/s3.ok`; the fab step of socket 3 fails without it.

## Rules that bite

- Heavy jobs only through `systemd-run --user --scope --quiet --slice=claude-route.slice <cmd>`
  (4 CPUs for everything of this project together).
- Never edit `rtl/s3/build.sh` or a script while it runs (bash reads it as it goes).
- Never `pkill` by pattern (other sessions run Quartus too): stop your own background task.
- Any change of pins, placement, planes or generated copper: stop the service, regenerate
  (`gen_socket3_assign.py`, `_t6`, `_t7`, `_t8`; C2 Mu: `gen_c2mu_s7.py`, `_s8.py`), run
  `hw/tools/check_board.py socket3|c2mu`, start the service again (`route_search.py --service
  <socket 3 board> <C2 Mu board>`): it starts afresh on a changed board by itself.
- RTL change in `rtl/s3`: `rtl/tools/s3_bus_test.sh`, `rtl/tools/s3_test.sh rtl/tests/x86/*.S
  rtl/tests/x86/c[1-4]*.c`, then `rtl/s3/build.sh rtl/build/s3bus bus` (minutes) before the
  full build.

## Steps

1. Quartus result (`tail rtl/build/s3/flow.log`, the build prints its summary at the end).
   Expected: timing met. The last full build failed on one path only (ADS# register to its pad,
   -0.87 ns); ADS# is an I/O register since. If a pin path still fails: `report_timing` it
   (pattern: `rtl/build/s3/path4.tcl`), keep the fix in the RTL / `rtl/s3/board.py`, do not move
   PHASE by more than ~0.3 ns (inputs and outputs share one margin). If `fpga_pins.py` complains
   about a supply name, add it to `RAILS` in `rtl/tools/fpga_pins.py` only after checking the
   voltage against `hw/socket3-cyclonev/power.md`.
   Then put the power estimate the build prints into plan/interposers.md D5 (heatsink on U1:
   Tj = 40 C + P x ~14 C/W must stay under 85 C).
2. Socket 3 routing. When a tool ends above 0 the next one starts by itself. If every tool
   ended above 0: not the budget (operator). List the open connections (DRC json of the board),
   find what they share (a strip between pins and edge, a layer, a chip) and fix the setup or
   the placement; 2026-11-11 round 4 of the first tool was at 26 open, mostly socket-side legs of
   the east and west columns (S_ nets from the lower chips to pin rows A / B and R / S).
   `--finish` also checks the bus copper against CLK's (50 mm): if it fails, look at the worst
   net's detour before touching the limit (the limit is the 0.6 ns of `rtl/s3/s3_top.sdc`).
3. Socket 3 fab: `python3 hw/tools/gen_socket_t9.py socket3` must end with PASS (board check,
   FPGA pins, DRC, BOM, live stock, package read back). Then set T8 / T9 to done in the status
   table of plan/interposers.md and write T10 (what was built, check results, open items, cost).
4. C2 Mu routing starts after socket 3 (hours per pass on this board). Same rule as step 2. Its
   earlier best was 31 open with a faulty plane setup. Then `python3 hw/tools/gen_c2mu_s9.py`.
5. Commit and push after each step (operator: no need to ask).

## Operator decisions 2026-11-11

- Bus unit before fab: SRESET, BS8# / BS16#, write-back snoop (HITM# / INV) + FLUSH#, clock stop
  in Stop Grant. Each needs its pin on the board (check `gen_socket3_assign.py` first: a missing
  pin is a board change, see "Rules that bite").
  All pins are on the board. BS8# / BS16#: in full (Intel486 Table 10-3, bursts too), although
  neither chipset drives them (operator, after being told). SRESET, FLUSH# and the snoop need the
  core: they are part of the memory-system step of M5 (plan/x86_core.md).
- CPU core: advance `rtl/x86` from M3 to M5 (real mode, interrupts, I/O) until it boots the BIOS
  in simulation, while routing runs; memory system first (plan/x86_core.md M5 list), then the ISA.
  KEN#: learned per 64 KB region (operator). Done 2026-11-11: BS8# / BS16#, PLL lock range and
  clock stop, RESET cache clear, A20M# in the core, uncached accesses + KEN#. Next: FLUSH# /
  WBINVD sweep, the snoop (HITM# / INV, write-back bursts with CACHE# in enhanced mode), SRESET
  with the M5 interrupt machinery. Every RTL change needs a new full build (`s3.ok`).
- Speed grade C8 vs C7: decide after the full Quartus build (step 1), ask the operator with the
  slack numbers.
- Socket 7 (`gen_socket7_t8.py` fails on purpose: S_VCC3 feed of PS2 / U3 in the S_VCC2 area of
  In4; no FAST group, no internal-pull emulation): after socket 3 and the C2 Mu are fabricated.
- Bench items: AS x4 boot from the 1 Gbit flash, JLCPCB placement preview by eye, GTL16612
  purchase route, Mill-Max header order.
