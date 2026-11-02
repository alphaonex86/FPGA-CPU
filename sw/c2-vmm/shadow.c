// Shadow RAM of 0xc0000-0xfffff as the 440BX maps it: PAM0-PAM6 (device
// 0:0 config 0x59-0x5f; 440BX datasheet 290633-001 sec. 3.3.17, Tables 3-2
// and 3-3) give each segment RE (reads from DRAM) and WE (writes to DRAM);
// otherwise the access goes to PCI. Segments: 0xc0000-0xeffff in 16 KB,
// 0xf0000-0xfffff in 64 KB. The guest's shadow DRAM is its RAM at the same
// address. KVM memslots per segment:
//   RE = 1                : the shadow RAM (read-only if WE = 0)
//   RE = 0, 0xe0000 and up: the BIOS ROM copy, read-only (code runs from it)
//   RE = 0, below         : none (the bus)
// A write that exits lands in the shadow RAM if WE = 1, else on the bus.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "shadow.h"

enum { NSEG = 13, SLOT0 = 8 };

static int vm_fd;
static uint8_t *shadow_ram;     // guest RAM at 0xc0000
static uint8_t *rom_e0000;      // the ROM copy's last 128 KB
static uint8_t pam[7];
static int mapped[NSEG];        // current memslot: 0 none, 1 RAM, 2 RAM read-only, 3 ROM
static uint32_t cf8;

static uint32_t seg_base(int s)
{
    return s < 12 ? 0xc0000 + 0x4000 * (uint32_t)s : 0xf0000;
}

static uint32_t seg_size(int s)
{
    return s < 12 ? 0x4000 : 0x10000;
}

// RE / WE bits of segment s: PAM1[3:0] = 0xc0000 ... PAM6[7:4] = 0xec000, PAM0[7:4] = 0xf0000
static int seg_attr(int s)
{
    return s < 12 ? pam[1 + s / 2] >> 4 * (s & 1) & 3 : pam[0] >> 4 & 3;
}

static int seg_of(uint32_t addr)
{
    if (addr < 0xc0000 || addr > 0xfffff) return -1;
    return addr >= 0xf0000 ? 12 : (int)(addr - 0xc0000) / 0x4000;
}

static void remap(int s)
{
    int attr = seg_attr(s);
    int want = attr & 1 ? (attr & 2 ? 1 : 2) : seg_base(s) >= 0xe0000 ? 3 : 0;
    if (want == mapped[s]) return;
    struct kvm_userspace_memory_region r = { .slot = SLOT0 + s, .guest_phys_addr = seg_base(s) };
    if (mapped[s] && ioctl(vm_fd, KVM_SET_USER_MEMORY_REGION, &r) < 0) {   // size 0: delete
        perror("c2-vmm: shadow memslot delete");
        exit(1);
    }
    mapped[s] = want;
    if (!want) return;
    r.memory_size = seg_size(s);
    r.flags = want == 1 ? 0 : KVM_MEM_READONLY;
    r.userspace_addr = (uint64_t)(want == 3 ? rom_e0000 + (seg_base(s) - 0xe0000)
                                            : shadow_ram + (seg_base(s) - 0xc0000));
    if (ioctl(vm_fd, KVM_SET_USER_MEMORY_REGION, &r) < 0) {
        perror("c2-vmm: shadow memslot");
        exit(1);
    }
}

void shadow_init(uint8_t *ram, uint8_t *rom, uint64_t rom_size)
{
    shadow_ram = ram + 0xc0000;
    rom_e0000 = rom + rom_size - 0x20000;
}

void shadow_bind(int vm)
{
    vm_fd = vm;
    memset(mapped, 0, sizeof(mapped));
    for (int s = 0; s < NSEG; s++) remap(s);
}

void shadow_reset(void)
{
    memset(pam, 0, sizeof(pam));
    cf8 = 0;
    for (int s = 0; s < NSEG; s++) remap(s);
}

void shadow_io_write(uint16_t port, int size, uint32_t value)
{
    if (port == 0xcf8 && size == 4) {
        cf8 = value;
        return;
    }
    // config mechanism 1, bus 0 device 0 function 0
    if (port < 0xcfc || port > 0xcff || (cf8 & 0x80fff800u) != 0x80000000u) return;
    for (int i = 0; i < size; i++) {
        uint32_t reg = (cf8 & 0xfc) + (port - 0xcfc) + (uint32_t)i;
        if (reg < 0x59 || reg > 0x5f) continue;
        pam[reg - 0x59] = (uint8_t)(value >> 8 * i);
        int first = reg == 0x59 ? 12 : 2 * (int)(reg - 0x5a);
        remap(first);
        if (reg != 0x59) remap(first + 1);
    }
}

int shadow_mmio_write(uint32_t addr, const uint8_t *data, int len)
{
    int s = seg_of(addr);
    if (s < 0 || !(seg_attr(s) & 2)) return 0;
    if (seg_of(addr + (uint32_t)len - 1) != s) {
        fprintf(stderr, "c2-vmm: write %08x/%d across shadow segments\n", addr, len);
        exit(1);
    }
    memcpy(shadow_ram + (addr - 0xc0000), data, (size_t)len);
    return 1;
}
