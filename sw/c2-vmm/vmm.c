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
#include <time.h>
#include <unistd.h>
#include "bus.h"
#include "shadow.h"

static int verbose;
static unsigned long long exits, smis;
static unsigned events;   // BUS_RESET / NMI / INIT / SMI polled, not yet handled

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

// the guest memory, and the KVM VM + vCPU over it (vm_open)
static struct {
    int kvm, vm, vcpu, run_size, a20m;
    struct kvm_run *run;
    uint8_t *ram, *rom;
    uint64_t ram_size, rom_size;
    uint32_t signature;
} g;

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

// retried when the 100 us tick interrupts it (KVM_RUN handles EINTR itself)
static int xioctl(int fd, unsigned long req, void *arg, const char *what)
{
    int r;
    while ((r = ioctl(fd, req, arg)) < 0 && errno == EINTR) {}
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

static double now_s(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + 1e-9 * (double)t.tv_nsec;
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

// the vCPU at power-on (KVM's reset state), restored at each board reset
// and INIT# (which keeps the x87 state): EDX = the signature, the reset
// vector FFFFFFF0h or with A6# 000FFFF0h
static struct kvm_regs reset_regs;
static struct kvm_sregs reset_sregs;
static struct kvm_fpu reset_fpu;
static struct kvm_vcpu_events reset_events;

static void cpu_reset(int low_vector, int power_on)
{
    struct kvm_regs regs = reset_regs;
    struct kvm_sregs sregs = reset_sregs;
    regs.rdx = g.signature;
    sregs.cs.base = low_vector ? 0xf0000 : 0xffff0000;
    xioctl(g.vcpu, KVM_SET_REGS, &regs, "KVM_SET_REGS");
    xioctl(g.vcpu, KVM_SET_SREGS, &sregs, "KVM_SET_SREGS");
    if (power_on) xioctl(g.vcpu, KVM_SET_FPU, &reset_fpu, "KVM_SET_FPU");
    xioctl(g.vcpu, KVM_SET_VCPU_EVENTS, &reset_events, "KVM_SET_VCPU_EVENTS");
}

// every status read: the edge events are kept until the main loop takes them
static unsigned poll_status(struct bus *b)
{
    unsigned st = b->status(b);
    events |= st & (BUS_RESET | BUS_NMI | BUS_INIT | BUS_SMI);
    return st;
}

// STPCLK#: the CPU stops after a Stop Grant Acknowledge until it is negated
// (or a board reset)
static void stop_grant(struct bus *b)
{
    b->special(b, BUS_STOP_GRANT);
    while (poll_status(b) & BUS_STPCLK && !(events & BUS_RESET)) usleep(10);
}

// the CPU halted or shut down until one of `until` (status bits and the
// pending events), STPCLK# acknowledged meanwhile; 0 after timeout_s (0: none)
static unsigned wait_for(struct bus *b, unsigned until, double timeout_s)
{
    double deadline = now_s() + timeout_s;
    for (;;) {
        unsigned st = poll_status(b) | events;
        if (st & until) return st;
        if (st & BUS_STPCLK) stop_grant(b);
        if (timeout_s && now_s() > deadline) return 0;
        usleep(10);
    }
}

// A20M#: the real-mode wraparound, 0x100000-0x10ffff onto 0-0xffff (all
// that real mode reaches; A20M# in protected mode is undefined)
static void set_a20m(int masked)
{
    masked = !!masked;
    if (masked == g.a20m) return;
    if (g.a20m != -1) add_slot(g.vm, 3, 0x100000, 0, NULL, 0);   // size 0: delete
    g.a20m = masked;
    add_slot(g.vm, 3, 0x100000, 0x10000, g.ram + (masked ? 0 : 0x100000), 0);
}

// a new VM and vCPU (in KVM's reset state) over the guest memory: at start,
// and after a shutdown, which leaves the vCPU unrunnable on an AMD host
// (KVM reinitialises its VMCB, the guest then makes no progress)
static void vm_open(void)
{
    g.vm = xioctl(g.kvm, KVM_CREATE_VM, 0, "KVM_CREATE_VM");
    // Intel VMX keeps private pages here (TSS: 3, EPT identity map: 1, used
    // without unrestricted guest); the defaults 0xfffbc000-0xfffbffff lie
    // inside a ROM of 512 KB or more, so put them just below the ROM
    uint64_t tss = 0x100000000ull - g.rom_size - 0x3000, identity_map = tss - 0x1000;
    xioctl(g.vm, KVM_SET_TSS_ADDR, (void *)tss, "KVM_SET_TSS_ADDR");
    xioctl(g.vm, KVM_SET_IDENTITY_MAP_ADDR, &identity_map, "KVM_SET_IDENTITY_MAP_ADDR");
    // RAM below the VGA hole and above 1 MB (its first 64 KB in slot 3,
    // set_a20m); 0xa0000-0xbffff is the board's, 0xc0000-0xfffff follows the
    // chipset's shadow map (shadow.c); the BIOS ROM at the top of 4 GB
    // (read-only: writes exit to the bus)
    add_slot(g.vm, 0, 0, 0xa0000, g.ram, 0);
    add_slot(g.vm, 1, 0x110000, g.ram_size - 0x110000, g.ram + 0x110000, 0);
    add_slot(g.vm, 2, 0x100000000ull - g.rom_size, g.rom_size, g.rom, 1);
    g.a20m = -1;
    set_a20m(0);
    shadow_bind(g.vm);

    g.vcpu = xioctl(g.vm, KVM_CREATE_VCPU, 0, "KVM_CREATE_VCPU");
    set_cpuid(g.kvm, g.vcpu, g.signature);
    xioctl(g.vcpu, KVM_GET_REGS, &reset_regs, "KVM_GET_REGS");
    xioctl(g.vcpu, KVM_GET_SREGS, &reset_sregs, "KVM_GET_SREGS");
    xioctl(g.vcpu, KVM_GET_FPU, &reset_fpu, "KVM_GET_FPU");
    xioctl(g.vcpu, KVM_GET_VCPU_EVENTS, &reset_events, "KVM_GET_VCPU_EVENTS");
    g.run_size = xioctl(g.kvm, KVM_GET_VCPU_MMAP_SIZE, 0, "KVM_GET_VCPU_MMAP_SIZE");
    g.run = mmap(NULL, (size_t)g.run_size, PROT_READ | PROT_WRITE, MAP_SHARED, g.vcpu, 0);
    if (g.run == MAP_FAILED) die("mmap kvm_run: %s", strerror(errno));
    int ring_page = ioctl(g.kvm, KVM_CHECK_EXTENSION, KVM_CAP_COALESCED_MMIO);
    if (ring_page <= 0 || ioctl(g.kvm, KVM_CHECK_EXTENSION, KVM_CAP_COALESCED_PIO) <= 0)
        die("KVM without coalesced MMIO / PIO");
    long page = sysconf(_SC_PAGESIZE);
    ring = (struct kvm_coalesced_mmio_ring *)((uint8_t *)g.run + ring_page * page);
    ring_max = (uint32_t)((page - sizeof(*ring)) / sizeof(ring->coalesced_mmio[0]));
    for (size_t i = 0; i < sizeof(coalesced) / sizeof(coalesced[0]); i++)
        xioctl(g.vm, KVM_REGISTER_COALESCED_MMIO, (void *)&coalesced[i], "KVM_REGISTER_COALESCED_MMIO");
}

static void vm_close(void)
{
    if (munmap(g.run, (size_t)g.run_size) || close(g.vcpu) || close(g.vm))
        die("closing the VM: %s", strerror(errno));
}

// a board reset (also at start): its end awaited, then what a CPU sees after
// it: PAM back to 0, the BIOS ROM read again (it may have been flashed), the
// vCPU at the reset vector, the events before it void; guest RAM is kept, as
// DRAM keeps its content. Returns the status.
static unsigned board_reset(struct bus *b)
{
    double deadline = now_s() + 5;
    unsigned st;
    while ((st = b->status(b)) & BUS_RESET) {
        if (now_s() > deadline) die("the board stays in reset (5 s), or the cartridge does not report");
        usleep(10);
    }
    bus_access(b, BUS_MEM, (uint32_t)(0x100000000ull - g.rom_size), g.rom, (int)g.rom_size, 0);
    shadow_reset();
    cpu_reset(st & BUS_LOW_VECTOR, 1);
    events = 0;
    fprintf(stderr, "c2-vmm: board reset, reset vector %s\n", st & BUS_LOW_VECTOR ? "000ffff0" : "fffffff0");
    return st;
}

static void on_tick(int sig)
{
    (void)sig;
}

static void report(void)
{
    fprintf(stderr, "c2-vmm: %llu exits, %llu SMIs ignored\n", exits, smis);
}

int main(int argc, char **argv)
{
    uint64_t ram_mb = 256, rom_kb = 256;
    g.signature = 0x683;   // Pentium III (Coppermine) cB0
    int opt, exit_port = -1;
    while ((opt = getopt(argc, argv, "m:r:s:e:v")) != -1) {
        if (opt == 'm') ram_mb = strtoull(optarg, NULL, 0);
        else if (opt == 'r') rom_kb = strtoull(optarg, NULL, 0);
        else if (opt == 's') g.signature = strtoul(optarg, NULL, 0);
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

    g.kvm = open("/dev/kvm", O_RDWR | O_CLOEXEC);
    if (g.kvm < 0) die("/dev/kvm: %s", strerror(errno));
    if (ioctl(g.kvm, KVM_GET_API_VERSION, 0) != KVM_API_VERSION) die("KVM API version");
    g.ram_size = ram_mb << 20;
    g.rom_size = rom_kb << 10;
    g.ram = alloc_mem(g.ram_size);
    g.rom = alloc_mem(g.rom_size);   // read from the board at each reset
    shadow_init(g.ram, g.rom, g.rom_size);
    vm_open();

    // an exit every 100 us even when the guest runs from RAM without I/O:
    // INTR is polled, coalesced writes are flushed (SA_RESTART: KVM_RUN
    // still returns EINTR)
    struct sigaction sa = { .sa_handler = on_tick, .sa_flags = SA_RESTART };
    if (sigaction(SIGALRM, &sa, NULL)) die("sigaction: %s", strerror(errno));
    struct itimerval tick = { .it_interval = { 0, 100 }, .it_value = { 0, 100 } };
    if (setitimer(ITIMER_REAL, &tick, NULL)) die("setitimer: %s", strerror(errno));
    atexit(report);

    board_reset(b);
    for (;;) {
        struct kvm_run *run = g.run;
        unsigned st = poll_status(b), ev = events;
        events = 0;
        if (ev & BUS_RESET) {
            st = board_reset(b);
            ev = 0;
        } else if (ev & BUS_INIT)
            cpu_reset(st & BUS_LOW_VECTOR, 0);
        if (ev & BUS_NMI) xioctl(g.vcpu, KVM_NMI, 0, "KVM_NMI");
        if (ev & BUS_SMI && !smis++) fprintf(stderr, "c2-vmm: SMI# ignored: no SMM yet\n");
        if (st & BUS_STPCLK) {
            stop_grant(b);
            continue;   // the events meanwhile
        }
        set_a20m(st & BUS_A20M);
        // INTR: acknowledged on the bus once the guest can take it
        run->request_interrupt_window = 0;
        if (st & BUS_INTR) {
            if (run->ready_for_interrupt_injection) {
                struct kvm_interrupt irq = { .irq = b->inta(b) };
                xioctl(g.vcpu, KVM_INTERRUPT, &irq, "KVM_INTERRUPT");
            } else
                run->request_interrupt_window = 1;
        }
        int r = ioctl(g.vcpu, KVM_RUN, 0), run_errno = errno;
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
            // no in-kernel irqchip: HLT returns here; the Halt Transaction,
            // then wait for INTR (with IF = 0 only an event can wake it)
            b->special(b, BUS_HALT);
            if (!run->if_flag) fprintf(stderr, "c2-vmm: halted with IF = 0\n");
            wait_for(b, (run->if_flag ? BUS_INTR : 0u) | BUS_RESET | BUS_INIT | BUS_NMI | BUS_SMI, 0);
            break;
        case KVM_EXIT_SHUTDOWN:
            // triple fault: the Shutdown Transaction, the chipset answers
            // with INIT# (PIIX4) or RESET#; a new vCPU (vm_open), so the x87
            // state is not kept here
            b->special(b, BUS_SHUTDOWN);
            if (!wait_for(b, BUS_RESET | BUS_INIT, 5))
                die("guest shutdown (triple fault), no INIT# or RESET# from the board in 5 s");
            vm_close();
            vm_open();
            break;
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
