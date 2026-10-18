# Cyclone V E A9 — 5CEBA9F23C8N / 5CEFA9F23C8N

F484 FineLine BGA, 23x23 mm, 1.0 mm pitch, 224 user I/O. "F" = 2 hard memory
controllers, "B" = none. A5/A7/A9 in F484 are footprint compatible.

- `docs/` datasheet, handbook vol 1 (I/O, clocks, config), overview, errata,
  pin connection guidelines, schematic review worksheet, package datasheet.
- `pins/` pin-out (txt/xls/pdf) and BSDL for both parts.
- `models/` IBIS, Early Power Estimator, 484-pin FBGA PCB layout, PLL map.
- `boards/` Cyclone V E dev kit guide and installer (schematics, layout).
- `reference/` ao486 (original, Cyclone IV) and ao486_MiSTer (Cyclone V).
- `software/` Quartus, downloaded by hand (Altera account login required).

## Software (manual download)

From altera.com/downloads, "Quartus Prime Lite Edition 25.1 Linux", put the full
tar in `software/` and check it: `cd software && sha1sum -c SHA1SUMS`.
The tar holds Quartus, Questa Starter, help and all Lite device files.
