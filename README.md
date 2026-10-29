# kinabalu-tools

Python tools for CAN, LIN, signal lists and code generation.

Detailed documentation: [docs/](docs/index.md)

## Installation

```sh
uv pip install -e .
# with dev tools (pytest, ruff)
uv sync --group dev
```

Requires Python >= 3.12. The CAN tools use a PEAK PCAN-USB adapter (`PCAN_USBBUS1`/`PCAN_USBBUS2`).

## Commands

### `can_send_trc`

Replays CAN trace files (`.trc`) with the timing recorded in the trace.

```sh
can_send_trc -c examples/cansendtrc_config.json <profile> [profile ...]
can_send_trc -c examples/cansendtrc_config.json -P        # list profiles
can_send_trc -c examples/cansendtrc_config.json -i a      # interactive, frame by frame
can_send_trc -c examples/cansendtrc_config.json -r 10 all # repeat 10 times
```

Config file (see [examples/cansendtrc_config.json](examples/cansendtrc_config.json)):

| Key | Meaning |
|---|---|
| `TrcDir` | Directory containing the trace files |
| `TrcFile` | Optional: trace file used for all busses (overrides per-bus `TrcFile`) |
| `CanBusses` | List of busses: `Hardware`, `Id`, `BaudRate`, optional `DataBaudRate` (CAN FD), `TrcFile` |
| `Profiles` | Profile name → list of `Hardware` names, or `"all"` |

Supported bitrates are defined in the timing table in `k6u/can/can_send_trc.py`
(CAN 2.0: 500k, 666.666k; CAN FD: 500k/1M, 500k/5M).

### `voice_to_can`

Sends a wave file as a sequence of CAN frames (4 samples per frame, mono 16-bit required).

```sh
voice_to_can [file.wav]   # default: bundled 200–800 Hz chirp
```

### `firmware_duplicates`

Finds copies of reference source files (`.c`, `.cpp`, `.h`, `.hpp`) in a directory tree
and writes a Markdown report with the number of changed lines per copy.

```sh
firmware_duplicates -r <refdir> -b <basedir> [-o report.md]
```
