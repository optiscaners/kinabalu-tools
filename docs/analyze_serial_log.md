# analyze_serial_log

Evaluates the counter lines of a box serial log and prints, for every CAN / LIN counter, the
received messages and matches per second, plus the sums for all CAN and all LIN counters,
and the total load of all tasks.

The log is the output of [serial_log_with_ts](../k6u/tools/serial_log_with_ts.py) (PC time
stamp per line).

## Usage

```sh
analyze_serial_log <logfile> [-s] [-d <sep>]
```

| Option | Meaning |
|---|---|
| `<logfile>` | Log file, `-` reads from stdin |
| `-s`, `--sums-only` | Print only the CAN / LIN sum lines |
| `-d`, `--sep <sep>` | Column separator (default: `, `), e.g. `-d ";"` for Excel |
| `-h` | Show help |

## Evaluated lines

All lines containing `match =`:

```text
2026-11-25T14:41:15.500715 : # ChassisCanCount (1): message = 759083, match = 407342, lost = 0, error = 0
2026-11-25T14:41:56.056832 : # SamLinCount (4): header = 4990, match = 0, init = 1, error = 0
```

The class is the word after `#` (`ChassisCanCount`, `SamLinCount`). The message counter is
`message` (CAN) or `header` (LIN).

For two consecutive lines of the same class:

| Value | Calculation |
|---|---|
| `delta_t` | `ts2 - ts1` (seconds) |
| `nb_msg_per_second` | `(message2 - message1) / delta_t` (CAN), `(header2 - header1) / delta_t` (LIN) |
| `nb_matches_per_second` | `(match2 - match1) / delta_t` |

## Output

```text
ts2, class, nb_msg_per_second, nb_matches_per_second
2026-11-25T14:41:23.117362, ChassisCanCount, 3127.7, 1681.4
...
2026-11-25T14:41:23.150958, SamLinCount, 132.7, 0.0
2026-11-25T14:41:23.150958, CAN, 28402.2, 11115.8
2026-11-25T14:41:23.150958, LIN, 336.2, 8.5
```

- One line per class and counter pair (rates with one decimal).
- After each block (every class once) a `CAN` line with the sums of all classes matching
  `*Can*Count`, and a `LIN` line with the sums of all classes matching `*Lin*Count`.
  `ts2` of the sum lines is the time stamp of the last line of the block.
- A block is complete when all classes have a new value; it ends at the latest when a class
  appears again.
- Lines containing `Hello World` (box start message, e.g. `# Hello World! (Pegasus20Gen2)`) are
  copied unchanged to stdout at their position, also with `-s`. They mark a box restart.

```sh
analyze_serial_log 3004_V65_real_can.log -s -d ";" > rates.csv
```

## Task load

From the task load lines of the box

```text
2026-11-25T14:41:15.480658 : # task load: 6 tasks, 5190 ms
2026-11-25T14:41:15.481595 : # task load: Main nr=2 prio=2 load=78.2% stackFree=6556
2026-11-25T14:41:15.483677 : # task load: Gsm nr=8 prio=1 load=8.4% stackFree=7200
...
2026-11-25T14:41:15.491280 : # task load: Tmr Svc nr=4 prio=7 load=0.0% stackFree=480
```

the load values of all tasks of a block except `IDLE` are added up (task = text between `load:`
and `nr=`). The result is the CPU load of the box.
After the last task of the block this line is printed (also with `-s`):

```text
2026-11-25T14:41:15.491280 : # task load: ALL nr=xx prio=xx load=86.6% stackFree=xx
```

- The task load lines of `Main` and `Gsm` are copied unchanged to stdout (also with `-s`),
  before the `ALL` line of their block (`TASK_LOAD_COPY` in the script).
- The time stamp is that of the last task line of the block.
- The block size is taken from the header line (`6 tasks`). Without a header, a block ends
  when a task appears again.
- Incomplete blocks (e.g. at the end of the log) are not summed.

## Counter resets

If a counter is smaller than in the previous line (box restart), the pair is skipped and a
message is printed to stderr once per block. Sum lines are only printed for complete blocks
(all classes valid), so no wrong sums are printed after a reset or for an incomplete
last block.
