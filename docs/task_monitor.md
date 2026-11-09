# task_monitor

Decodes the task monitor data of the firmware (per task: watchdog state and the log id call
stack) and optionally resolves the log ids to names from the firmware sources.

Python port of the C# `TaskMonitorDataViewer` (`estino-edge-embedded/Desktop/ToolsExtended/C#`);
the text output has the same format.

## Usage

```sh
task_monitor [-s <srcdir>]... [-v] [-o <outfile>] <file>
```

| Option | Meaning |
|---|---|
| `<file>` | Input file, the type is detected by its first bytes (see below) |
| `-s <srcdir>` | Firmware source directory scanned for log id names (repeatable) |
| `-v` | Verbose: show all log id slots, as the C# viewer (default: empty slots `0x00000000` are suppressed, also in text dumps) |
| `-o <outfile>` | Write the result to a file instead of stdout |
| `-h` | Show help |

| First bytes | Input | C# viewer menu |
|---|---|---|
| `0xFA 0xCE` | Data: `Ram_TaskMonitor.bin` or flash read `TaskMonitor` of the ServiceTool | Open Data... |
| `TM` | Flash format data: data flash file header + data (raw data flash content) | Open Flash Format Data... |
| other | Text dump (`Task List: ...`), passed through and annotated with names | – |

## Examples

Decode a RAM dump with names for Pegasus20:

```sh
set E=C:\Work\feature\HwGen29a\edge2
task_monitor -s %E%\Common -s %E%\Firmware -s %E%\Projects\Pegasus20\FirmwarePegasus20Gen2 Ram_TaskMonitor.bin
```

Annotate an existing text dump:

```sh
task_monitor -s %E%\Common -s %E%\Firmware -s %E%\Projects\Pegasus20\FirmwarePegasus20Gen2 logfile.txt
```

Output (shortened):

```text
 Task 0:
  Identity: Core0, Task, 513 (Gsm, id 2, prio 1)
  Watchdog Data:
   Has Timeout: True
   Is Serviced: False
   Timeout [ms]: 30000
  Log Data:
   Stack Depth: 2
   Log Id List:
*** Id 0: True, True, 0x03, 0x02, 0x03, 0x01  -> FirmwareMqtt/RemoteConnection/ProcessMqttStepPart/ProcessMqttStepEnterAction
*** Id 1: True, True, 0x03, 0x02, 0x03, 0x02  -> FirmwareMqtt/RemoteConnection/ProcessMqttStepPart/ProcessMqttStepProcessMessagesAction
+++ Id 2: False, True, 0x03, 0x02, 0x01, 0x0A  -> FirmwareMqtt/RemoteConnection/DefaultPart/RunBeginTransmitAction
```

## Data format

`TaskMonitorData` (firmware `Firmware/RtosFreeRtos/OptiScan/Tasks/TaskMonitor.h`), little endian.
The RAM read returns it directly; the flash read returns it without the data flash file header.

| Part | Content |
|---|---|
| Header (16 byte) | magic `0xFA 0xCE`, version major/minor, task count, watchdog data size, log data size (all `uint32` except the 4 bytes) |
| Timestamp (4 byte) | `time()` of the last watchdog task update |
| Task list | per task: identity, watchdog data (if size > 0), log data (if size > 0) |

The file must end exactly after the task list (error `EOF expected` otherwise).

The flash format prepends the 8 byte `DataFlashFileHeader`: magic `TM`, `uint16` data size,
`uint32` unused (must be 0). Bytes after the data (erased flash) are ignored.

- **Identity**: bits 31..24 category (Main, Task, Isr2, Isr1), 23..16 core, 15..0 sub id
  (for tasks `(id << 8) | priority`). With `-s`, the task name is taken from the
  `TASK_DEF_TASK/ISR1/ISR2/MAIN()` entries of `Task.def.h` (so include the project directory).
- **Watchdog data**: has timeout, is enabled, is serviced, is test enabled, timeout [ms].
- **Log data**: stack depth and `CFG_TASK_LOG_CAPACITY` log ids; the capacity is taken from the header.

A log id line reads `active, specific, library, module, part, action`:

| Field | Bits | Meaning |
|---|---|---|
| active | 31 | `True` = entry is on the call stack, `False` = popped (left over from an earlier call) |
| specific | 30 | `True` = firmware specific library / application, `False` = common library |
| library | 29..24 | library id, `0x3F` = application |
| module | 23..16 | `MODULE(name, index)` of the library or application |
| part | 15..8 | `OPTISCAN_SYSTEM_LOG_DECL_PART`, `0x00` if the action is declared directly on the module |
| action | 7..0 | `OPTISCAN_SYSTEM_LOG_DECL_ACTION` |

The active entries from index 0 up to `Stack Depth - 1` show where the task was when the dump was taken.
They are marked with `*** ` in red, popped entries (`False, True`) with `+++ ` in yellow (colors only when writing to a terminal, not with `-o`).

## Name resolution (`-s`)

The source directories are scanned (`.h`, `.hpp`, `.c`, `.cpp`; `build`, `cmake-build*`,
`_PACKAGE*` and `.git` are skipped) for:

- `#define <X>LibId OPTISCAN_SYSTEM_LOG_ID_DECL_LIB(OPTISCAN_SYSTEM_LOG(IdUnspecific|IdSpecific), 0xNN)`
- `#define <X>AppId OPTISCAN_SYSTEM_LOG(IdApplication)`
- `MODULE(name, 0xNN)` lists after a `#define MODULE(...) ... OPTISCAN_SYSTEM_LOG_ID_DECL_MODULE(<lib>, index)`
- `OPTISCAN_SYSTEM_LOG_DECL_PART(...)` and `OPTISCAN_SYSTEM_LOG_DECL_ACTION(...)`

Unknown fields are shown as hex.

## Differences to the C# viewer

- Task category 1 is shown as `Main` (firmware `TaskIdentity::Category`); the C# viewer shows `Idle`.
- Cores are always shown as `Core<n>`; the C# viewer only knows Core0..2 and prints bare numbers for Core3..5.
- If the watchdog or log data size is 0, the section is omitted; the C# viewer prints it filled with zeros.
- The magic `0xFA 0xCE` is checked (needed for the file type detection); the C# viewer does not check it.

## Known limitations

- Pass only **one** project directory: every application uses library `0x3F`, so scanning several
  projects mixes their module names (shown as `NameA|NameB`).
- Only `#if 0` blocks are excluded; other preprocessor conditions are ignored, so declarations
  under e.g. `CFG_TASK_LOG_EXTENDED` are resolved as well.
- A module name that exists in two libraries (e.g. `GsmTask`) assigns its parts and actions to both.
