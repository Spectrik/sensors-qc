import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TextIO

from .evaluators import FACTORIES, Evaluator, Reference

MAX_LINE_LENGTH = 4096
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?", re.ASCII)

class InputError(ValueError):
    """An invalid input record, with a source line number when available."""


@dataclass
class Statistics:
    sensors: int = 0
    readings: int = 0
    lines: int = 0


def number(token: str, line: int) -> Decimal:
    try:
        value = Decimal(token)
    except InvalidOperation:
        raise InputError(
            f"line {line}: invalid numeric value {token!r}"
        ) from None

    if not value.is_finite():
        raise InputError(
            f"line {line}: numeric value must be finite: {token!r}"
        )

    # Keep arithmetic within the supported sensor domain and Decimal precision.
    digits = value.as_tuple()
    exponent = digits.exponent

    if not isinstance(exponent, int):
        raise InputError(
            f"line {line}: numeric value must be finite: {token!r}"
        )

    if len(digits.digits) > 16 or abs(exponent) > 16:
        raise InputError(
            f"line {line}: numeric precision or exponent exceeds limits: {token!r}"
    )

    if value.copy_abs() > Decimal("1e12"):
        raise InputError(f"line {line}: numeric magnitude exceeds 1e12: {token!r}")

    return value


def evaluate(stream: TextIO, stats: Statistics | None = None) -> Iterator[tuple[str, str]]:
    stats = stats if stats is not None else Statistics()
    reference: Reference | None = None
    current: Evaluator | None = None
    current_name: str = ""
    seen: set[str] = set()

    def finish() -> tuple[str, str]:
        assert current is not None
        try:
            return current_name, current.classify()
        except ValueError as exc:
            raise InputError(f"line {stats.lines}: sensor {current_name!r}: {exc}") from None

    while True:
        raw = stream.readline(MAX_LINE_LENGTH + 1)
        if not raw:
            break

        stats.lines += 1
        line = stats.lines

        if len(raw) > MAX_LINE_LENGTH:
            raise InputError(f"line {line}: exceeds {MAX_LINE_LENGTH} characters")

        parts = raw.split()
        if not parts:  # Blank lines are explicitly allowed.
            continue

        # First line must be a reference header, e.g. "reference 70 45". Subsequent lines may be sensor headers or readings.
        if reference is None:
            if len(parts) != 3 or parts[0] != "reference":
                raise InputError(f"line {line}: expected 'reference <temperature> <humidity>'")

            reference = Reference(number(parts[1], line), number(parts[2], line))
            if not 0 <= reference.humidity <= 100:
                raise InputError(f"line {line}: reference humidity must be between 0 and 100")
            continue

        if parts[0] == "reference":
            raise InputError(f"line {line}: repeated reference header")

        # Line with a sensor type and name, e.g. "thermometer temp-1", starts a new sensor.
        factory = FACTORIES.get(parts[0])
        if factory is not None:
            if len(parts) != 2:
                raise InputError(f"line {line}: expected '<sensor-type> <sensor-name>'")
            name = parts[1]

            if name in seen:
                raise InputError(f"line {line}: duplicate sensor name {name!r}")

            # We finish the previous sensor before starting a new one, so that we can report its classification.
            if current is not None:
                yield finish()

            seen.add(name)
            current_name = name
            current = factory(reference)
            stats.sensors += 1
            continue

        if not TIMESTAMP.fullmatch(parts[0]):
            raise InputError(f"line {line}: unknown sensor type or invalid timestamp {parts[0]!r}")

        if len(parts) != 2:
            raise InputError(f"line {line}: expected '<timestamp> <value>'")

        try:
            datetime.fromisoformat(parts[0])
        except ValueError:
            raise InputError(f"line {line}: invalid calendar timestamp {parts[0]!r}") from None

        if current is None:
            raise InputError(f"line {line}: reading before a sensor header")

        value = number(parts[1], line)
        try:
            current.add(value)
        except ValueError as exc:
            raise InputError(f"line {line}: {exc}") from None
        stats.readings += 1

    if reference is None:
        raise InputError("missing reference header")

    if current is None:
        raise InputError("input contains no sensors")

    yield finish()
