# Prompt for the executing AI

Paste the block below into a new session started in
`/home/user/Desktop/CatchChallenger/FPGA-CPU`. Replace `<VARIANT>` (start with
`socket3-cyclonev`) and `<TASKS>` (e.g. `T0-T2`; one or two tasks per session
works best for a smaller model).

```text
Project: FPGA x86 CPU on an interposer that plugs into an original CPU socket.
Read AGENTS.md, then plan/interposers.md completely, before doing anything.
For Slot 1 (SC242) variants, additionally read plan/slot1.md — its decisions
run D8-D16 and its tasks are S0-S10.

Your job: execute tasks <TASKS> of plan/interposers.md for variant <VARIANT>.

How to work:
1. Do the tasks in order, one at a time. For each task: write the script under
   hw/tools/, run it, run the task's checks, fix until every check passes.
   A failed check is a failure, never skip or weaken it.
2. Every number you use (voltage, current, timing, dimension, pin) comes from a
   file in this repo: cite file + page or table next to it. If you cannot find it,
   say so; never guess.
3. Decisions D1-D7 and measurements M1-M3 belong to the operator: if a task needs
   one that is not recorded yet, stop and ask, with your recommendation and why.
4. Everything written to disk is English. Keep code short and readable, no
   speculative options, almost no comments. Generated files are only ever
   rewritten by their script.
5. Run kicad-cli with "nice -n 19". Check every command's exit code. Never use nohup.
6. Do not commit or push unless the operator asks.
7. When a task is done, put "done" in its cell of the Status table in
   plan/interposers.md.

End with a short report: tasks done, check results (pass/fail with numbers),
files created, questions for the operator.
```
