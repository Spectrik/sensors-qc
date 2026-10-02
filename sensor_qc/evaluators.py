from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite, sqrt
from typing import Protocol


class Evaluator(Protocol):
    def add(self, value: Decimal) -> None: ...
    def classify(self) -> str: ...


@dataclass(frozen=True)
class Reference:
    temperature: Decimal
    humidity: Decimal


@dataclass
class Thermometer:
    reference: Decimal
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def add(self, value: Decimal) -> None:
        x = float(value)
        if not isfinite(x):
            raise ValueError("temperature cannot be represented as a finite float")
        # Welford's numerically stable online variance algorithm.
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (x - self.mean)

        if not isfinite(self.mean) or not isfinite(self.m2):
            raise ValueError("temperature statistics overflowed")

    def classify(self) -> str:
        if not self.n:
            raise ValueError("sensor has no readings")

        stddev = sqrt(max(0.0, self.m2 / self.n))  # population standard deviation
        if abs(self.mean - float(self.reference)) <= 0.5:
            if stddev < 3:
                return "ultra precise"
            if stddev < 5:
                return "very precise"

        return "precise"


@dataclass
class Humidity:
    reference: Decimal
    n: int = 0
    invalid: bool = False

    def add(self, value: Decimal) -> None:
        self.n += 1
        # Compare decimal values exactly; 44.0 and 46.0 are allowed for reference 45.
        if abs(value - self.reference) > Decimal(1):
            self.invalid = True

    def classify(self) -> str:
        if not self.n:
            raise ValueError("sensor has no readings")
        return "discard" if self.invalid else "keep"


class CarbonMonoxide:
    def add(self, value: Decimal) -> None:
        raise NotImplementedError(
            "CO sensor evaluation criteria are not specified."
        )

    def classify(self) -> str:
        raise NotImplementedError(
            "CO sensor evaluation criteria are not specified."
        )

FACTORIES: dict[str, Callable[[Reference], Evaluator]] = {
    "thermometer": lambda ref: Thermometer(ref.temperature),
    "humidity": lambda ref: Humidity(ref.humidity),
}
