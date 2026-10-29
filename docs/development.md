# Development

## Setup

```sh
uv venv
uv sync --group dev        # installs the package (editable) plus pytest and ruff
```

## Lint

```sh
uv run ruff check k6u
uv run ruff format k6u
```

## Project layout

```
k6u/
  can/
    can_send_trc.py         # can_send_trc command
    voice_to_can.py         # voice_to_can command
  tools/
    firmware_duplicates.py  # firmware_duplicates command
  data/                     # files shipped with the package (test wave file)
examples/                   # example configuration files
docs/                       # this documentation
```

## Adding a new command

1. Add a module with a `main()` function below `k6u/`.
2. Register it in `[project.scripts]` in `pyproject.toml`.
3. Reinstall (`uv pip install -e .`) so the command is created.
4. Add a page to `docs/` and link it from [index.md](index.md).
