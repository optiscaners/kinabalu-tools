# kinabalu-tools

Python tools for CAN, LIN, signal lists and code generation.

Detailed documentation: [docs/](docs/index.md)

## Installation

```sh
uv pip install -e .
# with dev tools (pytest, ruff)
uv sync --group dev
```

Requires Python >= 3.12. 

The CAN tools use a PEAK PCAN-USB adapter (`PCAN_USBBUS1`/`PCAN_USBBUS2`).

## Commands

### `can_send_trc`

Replays CAN trace files (`.trc`) with the timing recorded in the trace.

[... read more ...](docs/can_send_trc.md)

### `voice_to_can`

Sends a wave file as a sequence of CAN frames (4 samples per frame, mono 16-bit required).

[... read more ...](docs/voice_to_can.md)

### `firmware_duplicates`

Finds copies of reference source files (`.c`, `.cpp`, `.h`, `.hpp`) in a directory tree
and writes a Markdown report with the number of changed lines per copy.

[... read more ...](docs/firmware_duplicates.md)

### `box_status`

Monitors the online status of boxes via MQTT (`<topic>/<box>/Status/Connection`) in a
full-screen, htop-like terminal view.

[... read more ...](docs/box_status.md)


### `lin_send_ldf`

Send LIN frames from an LDF file over a PLin-compatible interface.

[... read more ...](docs/lin_send_ldf.md)