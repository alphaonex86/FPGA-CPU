// Slot 1 C2 VMM (plan/slot1_c2.md): one KVM vCPU runs the board's BIOS and
// OS; guest RAM is ours, every other access is a bus cycle on the board.
// Usage: c2-vmm [-m MB] [-r ROM_KB] [-s signature] [-e port] [-v] sim <rom.bin> | fpga <bar0>
// -e: exit with the byte the guest writes to that I/O port (test ROMs)
#include <errno.h>
#include <fcntl.h>
#include <linux/kvm.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/time.h>
#include <unistd.h>
#include "bus.h"
#include "shadow.h"

static int verbose;
static unsigned long long exits;

// Writes that need no exit (KVM coalesced MMIO / PIO): the ATA data ports
// (KVM exits once per element of a rep outs) and the VGA memory window.
// Every exit flushes them to the bus first, so bus order is program order.
static const struct kvm_coalesced_mmio_zone coalesced[] = {
    { .addr = 0x1f0, .size = 4, .pio = 1 },
    { .addr = 0x170, .size = 4, .pio = 1 },
    { .addr = 0xa0000, .size = 0x20000 },
};
static struct kvm_coalesced_mmio_ring *ring;
static uint32_t ring_max;

__attribute__((noreturn, format(printf, 1, 2))) static void die(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "c2-vmm: ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
    exit(1);
}

static int xioctl(int fd, unsigned long req, void *arg, const char *what)
{
    int r = ioctl(fd, req, arg);
    if (r < 0) die("%s: %s", what, strerror(errno));
    return r;
}

static void add_slot(int vm, int slot, uint64_t gpa, uint64_t size, void *host, int readonly)
{
    struct kvm_userspace_memory_region r = {
        .slot = slot, .flags = readonly ? KVM_MEM_READONLY : 0,
        .guest_phys_addr = gpa, .memory_size = size, .userspace_addr = (uint64_t)host,
    };
    xioctl(vm, KVM_SET_USER_MEMORY_REGION, &r, "KVM_SET_USER_MEMORY_REGION");
}

static void *alloc_mem(uint64_t size)
{
    void *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) die("mmap %llu bytes: %s", (unsigned long long)size, strerror(errno));
    return p;
}

// CPUID as the board expects: host features masked to a Pentium III, the
// given signature (family/model/stepping, CPUID.1:EAX)
static void set_cpuid(int kvm, int vcpu, uint32_t signature)
{
    enum { N = 100 };
    struct kvm_cpuid2 *c = calloc(1, sizeof(*c) + N * sizeof(struct kvm_cpuid_entry2));
    if (!c) die("calloc");
    c->nent = N;
    xioctl(kvm, KVM_GET_SUPPORTED_CPUID, c, "KVM_GET_SUPPORTED_CPUID");
    // FPU VME DE PSE TSC MSR PAE MCE CX8 SEP MTRR PGE MCA CMOV PAT PSE36 MMX
    // FXSR SSE (bits 0-8, 11-17, 23-25; no local APIC is emulated)
    const uint32_t p3_edx = 0x0383f9ff;
    uint32_t n = 0;
    for (uint32_t i = 0; i < c->nent; i++) {
        struct kvm_cpuid_entry2 *e = &c->entries[i];
        if (e->function > 2) continue;
        if (e->function == 0) e->eax = 2;
        if (e->function == 1) {
            e->eax = signature;
            e->ebx = 0;
            e->ecx = 0;
            e->edx &= p3_edx;
        }
        c->entries[n++] = *e;
    }
    c->nent = n;
    xioctl(vcpu, KVM_SET_CPUID2, c, "KVM_SET_CPUID2");
    free(c);
}

// a guest access of any length as aligned 1/2/4-byte bus cycles
static void bus_access(struct bus *b, int space, uint32_t addr, uint8_t *data, int len, int write)
{
    while (len > 0) {
        int size = 4;
        while (size > 1 && ((addr & (size - 1)) || size > len)) size >>= 1;
        uint32_t v = 0;
        if (write) {
            memcpy(&v, data, size);
            b->write(b, space, addr, size, v);
        } else {
            v = b->read(b, space, addr, size);
            memcpy(data, &v, size);
        }
        if (verbose)
            fprintf(stderr, "%s %s %08x/%d = %0*x\n", space == BUS_IO ? "io " : "mem",
                    write ? "wr" : "rd", addr, size, 2 * size, v);
        addr += size;
        data += size;
        len -= size;
    }
}

static void flush_coalesced(struct bus *b)
{
    uint32_t first = ring->first;
    while (first != __atomic_load_n(&ring->last, __ATOMIC_ACQUIRE)) {
        struct kvm_coalesced_mmio *m = &ring->coalesced_mmio[first];
        if (m->pio) shadow_io_write((uint16_t)m->phys_addr, (int)m->len, *(uint32_t *)m->data);
        bus_access(b, m->pio ? BUS_IO : BUS_MEM, (uint32_t)m->phys_addr, m->data, (int)m->len, 1);
        first = (first + 1) % ring_max;
        __atomic_store_n(&ring->first, first, __ATOMIC_RELEASE);
    }
}

static void on_tick(int sig)
{
    (void)sig;
}

static void report(void)
{
    fprintf(stderr, "c2-vmm: %llu exits\n", exits);
}

int main(int argc, char **argv)
{
    uint64_t ram_mb = 256, rom_kb = 256;
    uint32_t signature = 0x683;   // Pentium III (Coppermine) cB0
    int opt, exit_port = -1;
    while ((opt = getopt(argc, argv, "m:r:s:e:v")) != -1) {
        if (opt == 'm') ram_mb = strtoull(optarg, NULL, 0);
        else if (opt == 'r') rom_kb = strtoull(optarg, NULL, 0);
        else if (opt == 's') signature = strtoul(optarg, NULL, 0);
        else if (opt == 'e') exit_port = (int)strtol(optarg, NULL, 0);
        else if (opt == 'v') verbose = 1;
        else die("usage: c2-vmm [-m MB] [-r ROM_KB] [-s signature] [-e port] [-v] sim <rom.bin> | fpga <bar0>");
    }
    if (argc - optind != 2) die("usage: c2-vmm [-m MB] [-r ROM_KB] [-s signature] [-e port] [-v] sim <rom.bin> | fpga <bar0>");
    if (ram_mb < 2 || ram_mb > 3072) die("RAM %llu MB: 2 .. 3072", (unsigned long long)ram_mb);
    if (rom_kb < 128 || rom_kb > 1024 || (rom_kb & (rom_kb - 1))) die("ROM %llu KB: a power of 2, 128 .. 1024",
                                                                       (unsigned long long)rom_kb);
    struct bus *b = !strcmp(argv[optind], "sim") ? bus_sim_open(argv[optind + 1])
                  : !strcmp(argv[optind], "fpga") ? bus_fpga_open(argv[optind + 1])
#ifdef C2_RTL
                  : !strcmp(argv[optind], "rtl") ? bus_rtl_open(argv[optind + 1])
#endif
                  : NULL;
    if (!b) die("backend %s: sim or fpga (rtl in the test_rtl.sh build) failed to open", argv[optind]);

    int kvm = open("/dev/kvm", O_RDWR | O_CLOEXEC);
    if (kvm < 0) die("/dev/kvm: %s", strerror(errno));
    if (ioctl(kvm, KVM_GET_API_VERSION, 0) != KVM_API_VERSION) die("KVM API version");
    int vm = xioctl(kvm, KVM_CREATE_VM, 0, "KVM_CREATE_VM");
    uint64_t ram_size = ram_mb << 20, rom_size = rom_kb << 10;
    // Intel VMX keeps private pages here (TSS: 3, EPT identity map: 1, used
    // without unrestricted guest); the defaults 0xfffbc000-0xfffbffff lie
    // inside a ROM of 512 KB or more, so put them just below the ROM
    uint64_t tss = 0x100000000ull - rom_size - 0x3000, identity_map = tss - 0x1000;
    xioctl(vm, KVM_SET_TSS_ADDR, (void *)tss, "KVM_SET_TSS_ADDR");
    xioctl(vm, KVM_SET_IDENTITY_MAP_ADDR, &identity_map, "KVM_SET_IDENTITY_MAP_ADDR");

    // RAM below the VGA hole and above 1 MB; 0xa0000-0xbffff is the
    // board's, 0xc0000-0xfffff follows the chipset's shadow map (shadow.c)
    uint8_t *ram = alloc_mem(ram_size);
    add_slot(vm, 0, 0, 0xa0000, ram, 0);
    add_slot(vm, 1, 0x100000, ram_size - 0x100000, ram + 0x100000, 0);
    // the BIOS ROM, read once from the board, at the top of 4 GB
    // (read-only: writes exit to the bus)
    uint8_t *rom = alloc_mem(rom_size);
    bus_access(b, BUS_MEM, (uint32_t)(0x100000000ull - rom_size), rom, (int)rom_size, 0);
    add_slot(vm, 2, 0x100000000ull - rom_size, rom_size, rom, 1);
    shadow_init(vm, ram, rom, rom_size);

    int vcpu = xioctl(vm, KVM_CREATE_VCPU, 0, "KVM_CREATE_VCPU");
    set_cpuid(kvm, vcpu, signature);
    int run_size = xioctl(kvm, KVM_GET_VCPU_MMAP_SIZE, 0, "KVM_GET_VCPU_MMAP_SIZE");
    struct kvm_run *run = mmap(NULL, run_size, PROT_READ | PROT_WRITE, MAP_SHARED, vcpu, 0);
    if (run == MAP_FAILED) die("mmap kvm_run: %s", strerror(errno));
    int ring_page = ioctl(kvm, KVM_CHECK_EXTENSION, KVM_CAP_COALESCED_MMIO);
    if (ring_page <= 0 || ioctl(kvm, KVM_CHECK_EXTENSION, KVM_CAP_COALESCED_PIO) <= 0)
        die("KVM without coalesced MMIO / PIO");
    long page = sysconf(_SC_PAGESIZE);
    ring = (struct kvm_coalesced_mmio_ring *)((uint8_t *)run + ring_page * page);
    ring_max = (uint32_t)((page - sizeof(*ring)) / sizeof(ring->coalesced_mmio[0]));
    for (size_t i = 0; i < sizeof(coalesced) / sizeof(coalesced[0]); i++)
        xioctl(vm, KVM_REGISTER_COALESCED_MMIO, (void *)&coalesced[i], "KVM_REGISTER_COALESCED_MMIO");

    // an exit every 100 us even when the guest runs from RAM without I/O:
    // INTR is polled, coalesced writes are flushed (SA_RESTART: KVM_RUN
    // still returns EINTR)
    struct sigaction sa = { .sa_handler = on_tick, .sa_flags = SA_RESTART };
    if (sigaction(SIGALRM, &sa, NULL)) die("sigaction: %s", strerror(errno));
    struct itimerval tick = { .it_interval = { 0, 100 }, .it_value = { 0, 100 } };
    if (setitimer(ITIMER_REAL, &tick, NULL)) die("setitimer: %s", strerror(errno));
    atexit(report);

    for (;;) {
        // INTR: acknowledged on the bus once the guest can take it
        run->request_interrupt_window = 0;
        if (b->intr(b)) {
            if (run->ready_for_interrupt_injection) {
                struct kvm_interrupt irq = { .irq = b->inta(b) };
                xioctl(vcpu, KVM_INTERRUPT, &irq, "KVM_INTERRUPT");
            } else
                run->request_interrupt_window = 1;
        }
        int r = ioctl(vcpu, KVM_RUN, 0), run_errno = errno;
        exits++;
        flush_coalesced(b);   // older than the exit's own access
        if (r < 0) {
            if (run_errno == EINTR) continue;
            die("KVM_RUN: %s", strerror(run_errno));
        }
        switch (run->exit_reason) {
        case KVM_EXIT_IO: {
            uint8_t *p = (uint8_t *)run + run->io.data_offset;
            int out = run->io.direction == KVM_EXIT_IO_OUT;
            if (run->io.count > 1) {   // string I/O: one batch
                for (uint32_t i = 0; out && i < run->io.count; i++) {
                    uint32_t v = 0;
                    memcpy(&v, p + i * run->io.size, run->io.size);
                    shadow_io_write(run->io.port, run->io.size, v);
                }
                b->io_rep(b, run->io.port, run->io.size, run->io.count, p, out);
                break;
            }
            for (uint32_t i = 0; i < run->io.count; i++, p += run->io.size) {
                if (out) {
                    uint32_t v = 0;
                    memcpy(&v, p, run->io.size);
                    shadow_io_write(run->io.port, run->io.size, v);
                }
                bus_access(b, BUS_IO, run->io.port, p, run->io.size, out);
                if (out && run->io.port == exit_port) exit(*p);
            }
            break;
        }
        case KVM_EXIT_MMIO:
            if (run->mmio.phys_addr >> 32) die("MMIO above 4 GB: %llx", (unsigned long long)run->mmio.phys_addr);
            if (!run->mmio.is_write
                || !shadow_mmio_write((uint32_t)run->mmio.phys_addr, run->mmio.data, (int)run->mmio.len))
                bus_access(b, BUS_MEM, (uint32_t)run->mmio.phys_addr, run->mmio.data, (int)run->mmio.len,
                           run->mmio.is_write);
            break;
        case KVM_EXIT_IRQ_WINDOW_OPEN:
        case KVM_EXIT_INTR:
            break;
        case KVM_EXIT_HLT:
            // no in-kernel irqchip: HLT returns here; wait for INTR
            if (!run->if_flag) die("HLT with interrupts disabled");
            while (!b->intr(b)) usleep(10);
            break;
        case KVM_EXIT_SHUTDOWN:
            die("guest shutdown (triple fault)");
        case KVM_EXIT_FAIL_ENTRY:
            die("entry failed, reason 0x%llx",
                (unsigned long long)run->fail_entry.hardware_entry_failure_reason);
        case KVM_EXIT_INTERNAL_ERROR:
            die("KVM internal error, suberror %u", run->internal.suberror);
        default:
            die("unhandled exit reason %u", run->exit_reason);
        }
    }
}
