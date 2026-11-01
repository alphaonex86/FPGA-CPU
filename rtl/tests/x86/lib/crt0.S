# Entry of C tests (x86_test.sh): main's result stays in EAX, checked at HLT.
        .text
        .globl _start
_start: call main
        hlt
