# firmware_duplicates

Finds copies of reference source files in a firmware tree and reports how much each copy differs
from the reference.

## Usage

```sh
firmware_duplicates -r <refdir> -b <basedir> [-o <reportfile>]
```

| Option | Meaning |
|---|---|
| `-r <refdir>` | Reference directory (the "original" sources) |
| `-b <basedir>` | Directory tree scanned for copies |
| `-o <reportfile>` | Markdown report (default: `report.md`) |
| `-v` | Reserved for a more verbose report (not implemented yet) |
| `-h` | Show help |

## How it works

1. All `.c`, `.cpp`, `.h`, `.hpp` files below `refdir` become reference candidates.
2. All files with these extensions below `basedir` are matched **by file name** against the candidates:
   - same name as a reference file → recorded as a copy of it
   - unknown name → added as an extra candidate (a file that only exists in `basedir`)
3. Each copy is diffed line by line against its reference (inserted and deleted lines are counted).
4. The report is written.

`refdir` may lie inside `basedir`; the reference files themselves are not counted as copies.

## Report sections

| Section | Content |
|---|---|
| Overview | Number of candidates (in/outside the reference dir) and of copies found |
| Derived Files | Reference files with at least one modified copy; per copy: changed/inserted/deleted lines |
| Unchanged Files | Reference files whose copies are all identical |
| Unique Files | Files without any copy |

Paths are shown relative to `basedir`; files outside of it are shown with their full path.

## Known limitations

- Files are matched by name only. Several different files with the same name (e.g. `main.c`)
  in `basedir` are all treated as copies of the same reference.
- If `refdir` contains the same file name twice, only the first one is used as reference
  (a warning is printed). `refdir` should therefore not contain `cmake-build*` folders.
- Files are read as UTF-8; invalid bytes are replaced and may show up as changed lines.
