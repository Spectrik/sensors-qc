import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from typing import IO, TextIO

from .parser import InputError, Statistics, evaluate


def log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), file=sys.stderr)


def write_json(source: TextIO, destination: IO[str], stats: Statistics) -> None:
    destination.write("{\n")
    first = True
    for name, classification in evaluate(source, stats):
        if not first:
            destination.write(",\n")
        destination.write(f"  {json.dumps(name)}: {json.dumps(classification)}")
        first = False
    destination.write("\n}\n")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify manufacturing sensor logs.")
    parser.add_argument("--input", default="-", help="UTF-8 input file; '-' reads stdin")
    parser.add_argument("--output", default="-", help="JSON output file; '-' writes stdout")
    args = parser.parse_args(argv)

    stats = Statistics()
    started = time.monotonic()
    temporary_path: str | None = None

    try:
        with ExitStack() as stack:
            source = sys.stdin if args.input == "-" else stack.enter_context(
                open(args.input, encoding="utf-8")
            )

            if args.output == "-":
                # Spill to disk at 1 MiB. Invalid input never emits partial JSON.
                staged = stack.enter_context(tempfile.SpooledTemporaryFile(
                    max_size=1024 * 1024, mode="w+", encoding="utf-8"
                ))
                write_json(source, staged, stats)
                staged.seek(0)
                shutil.copyfileobj(staged, sys.stdout)
                sys.stdout.flush()
            else:
                output = Path(args.output)
                staged = stack.enter_context(tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=output.parent,
                    prefix=f".{output.name}.", suffix=".tmp", delete=False
                ))
                temporary_path = staged.name
                write_json(source, staged, stats)
                staged.flush()
                os.fsync(staged.fileno())
                staged.close()
                # Source is closed before replacement, including input == output.
                stack.close()
                os.replace(temporary_path, output)
                temporary_path = None
        log("evaluation_completed", sensors=stats.sensors, readings=stats.readings,
            lines=stats.lines, duration_seconds=round(time.monotonic() - started, 6))
        return 0
    except (InputError, UnicodeError) as exc:
        log("evaluation_failed", kind="invalid_input", error=str(exc), lines=stats.lines)
        return 2
    except OSError as exc:
        log("evaluation_failed", kind="io_error", error=str(exc))
        return 1
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def main() -> None:
    raise SystemExit(run())
