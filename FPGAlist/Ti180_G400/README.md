# Efinix Titanium Ti180 — TI180G400C3

400-ball FBGA, 16x16 mm, 0.8 mm pitch, 274 GPIO: 200 HSIO (1.2-1.8 V, VREF
inputs) + 74 HVIO (3.3 V). No hard DRAM controller in G400 (J484 has LPDDR4).

- `docs/` datasheet, Titanium overview, packaging, interfaces, primitives,
  configuration, power estimator, PLL/clocking, reset, boundary scan, IBIS,
  VQPS, HyperRAM controller, advisory ADV-2409-001.
- `pins/` pinout for every Ti180 package (sheet Ti180G400).
- `boards/` M484 and J484 dev kit guides and schematics (power/config reference).
- `software/docs/` Efinity user guides.

## Software (manual download)

Efinity needs a free Efinix Support Center account: download the latest Linux
`efinity-<version>-*.tar.bz2` into `software/`, then
`tar -xjf efinity-*.tar.bz2` (no licence needed; see `software/docs/efinity_install_ug.pdf`).
