#!/usr/bin/env python3
"""Usage: vcd_scope.py <in.vcd> <out.vcd> <scope path in> <scope path out> <its module> <rtl.sv>...
Keeps one scope of a Verilator VCD (e.g. TOP.core_top.core) with everything under it, placed at
another path (e.g. s3_top.core: the instance in the Quartus netlist), for quartus_pow. Quartus names
struct fields and generate blocks with a dot inside one instance (rob[3].value, alu[0].u_alu), while
Verilator writes them as scopes: only module instances (a name its parent module instantiates in
the RTL) stay scopes, every other scope is folded into the names below it. Value changes of signals
outside the kept scope are dropped."""
import re
import sys

INST = re.compile(r'^\s*(\w+)\s*(?:#\s*\(.*?\)\s*)?(\w+)\s*\(', re.M | re.S)


def instances(files):
    """{module: {instance name: its module}} from the RTL (one module per file)."""
    srcs = {}
    for path in files:
        src = re.sub(r'//[^\n]*', '', open(path).read())
        for m in re.findall(r'^\s*module\s+(\w+)', src, re.M):
            srcs[m] = src
    return {m: {i: c for c, i in INST.findall(src) if c in srcs} for m, src in srcs.items()}


def main():
    src, dst, path_in, path_out, top = sys.argv[1:6]
    inst = instances(sys.argv[6:])
    if top not in inst:
        sys.exit('module %s not in the RTL files' % top)
    want = path_in.split('.')
    stack = []          # scopes of the input: (name, kind) with kind in 'want', 'inst', 'fold', 'out'
    mods = []           # the module of each kept scope
    keep = set()
    with open(src) as f, open(dst, 'w') as o:
        for line in f:                                   # header
            t = line.split()
            if t[:1] == ['$scope']:
                names = [s[0] for s in stack] + [t[2]]
                if names == want:
                    kind = 'want'
                    mods.append(top)
                    for name in path_out.split('.'):
                        o.write('$scope module %s $end\n' % name)
                elif names[:len(want)] != want:
                    kind = 'out'
                elif t[2] in inst[mods[-1]]:
                    kind = 'inst'
                    mods.append(inst[mods[-1]][t[2]])
                    o.write('$scope module %s%s $end\n' % (fold_prefix(stack, want), t[2]))
                else:
                    kind = 'fold'
                stack.append((t[2], kind))
            elif t[:1] == ['$upscope']:
                name, kind = stack.pop()
                if kind == 'want':
                    o.write('$upscope $end\n' * len(path_out.split('.')))
                    mods.pop()
                elif kind == 'inst':
                    o.write('$upscope $end\n')
                    mods.pop()
            elif t[:1] == ['$var']:
                if any(k == 'want' for _, k in stack):
                    keep.add(t[3])
                    t[4] = fold_prefix(stack, want) + t[4]
                    o.write(' '.join(t) + '\n')
            elif t[:1] == ['$enddefinitions']:
                o.write(line)
                break
            elif not stack:
                o.write(line)                            # $version, $timescale
        if not keep:
            sys.exit('no signal under scope %s' % path_in)
        for line in f:                                   # value changes
            c = line[0]
            if c in '#$':
                o.write(line)
            elif c in 'bBrR':
                if line.split()[1] in keep:
                    o.write(line)
            elif line[1:].strip() in keep:
                o.write(line)


def fold_prefix(stack, want):
    """The folded scopes since the last kept scope, as a name prefix: 'rob[3].flags.'"""
    prefix = []
    for name, kind in stack:
        if kind == 'fold':
            prefix.append(name)
        elif kind in ('inst', 'want'):
            prefix = []
    return ''.join(p + '.' for p in prefix)


if __name__ == '__main__':
    main()
