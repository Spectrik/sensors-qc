import contextlib
import io
import json
import random
import statistics
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from sensor_qc.cli import run
from sensor_qc.evaluators import Humidity, Thermometer
from sensor_qc.parser import MAX_LINE_LENGTH, InputError, Statistics, evaluate, number

ROOT = Path(__file__).resolve().parents[1]


def classify(values, reference="70"):
    sensor = Thermometer(Decimal(reference))
    for value in values:
        sensor.add(Decimal(str(value)))
    return sensor.classify()


class EvaluatorTests(unittest.TestCase):
    def test_mean_boundary_inclusive(self):
        self.assertEqual(classify([70.5]), "ultra precise")
        self.assertEqual(classify([69.5]), "ultra precise")
        self.assertEqual(classify([70.5001]), "precise")

    def test_standard_deviation_strict_thresholds(self):
        self.assertEqual(classify([67, 73]), "very precise")  # sigma == 3
        self.assertEqual(classify([65, 75]), "precise")       # sigma == 5
        self.assertEqual(classify([67.1, 72.9]), "ultra precise")
        self.assertEqual(classify([65.1, 74.9]), "very precise")

    def test_population_not_sample_variance(self):
        self.assertEqual(classify([67.5, 72.5]), "ultra precise")

    def test_wrong_mean_even_if_stable(self):
        self.assertEqual(classify([80, 80]), "precise")

    def test_welford_matches_independent_reference(self):
        rng = random.Random(42)
        values = [rng.uniform(50, 90) for _ in range(10000)]
        sensor = Thermometer(Decimal(70))
        for value in values:
            sensor.add(Decimal(str(value)))
        self.assertAlmostEqual(sensor.mean, statistics.mean(values), places=10)
        self.assertAlmostEqual(sensor.m2 / sensor.n, statistics.pvariance(values), places=9)

    def test_humidity_exact_decimal_boundaries(self):
        for values, expected in [([44, 46], "keep"),
                                 (["43.9999999999999"], "discard"),
                                 (["46.0000000000001"], "discard"),
                                 ([45, 43, 45], "discard")]:
            with self.subTest(values=values):
                sensor = Humidity(Decimal(45))
                for value in values:
                    sensor.add(Decimal(str(value)))
                self.assertEqual(sensor.classify(), expected)

    def test_no_measurements(self):
        for sensor in (Thermometer(Decimal(70)), Humidity(Decimal(45))):
            with self.assertRaises(ValueError):
                sensor.classify()


class ParserTests(unittest.TestCase):
    def test_assignment_sample(self):
        stats = Statistics()
        with (ROOT / "examples/sample.log").open() as stream:
            actual = dict(evaluate(stream, stats))
        expected = json.loads((ROOT / "examples/expected.json").read_text())
        self.assertEqual(actual, expected)
        self.assertEqual((stats.sensors, stats.readings), (4, 26))

    def test_blank_lines_crlf_and_final_block_without_newline(self):
        stream = io.StringIO("\r\nreference 70 45\r\nhumidity h\r\n\r\n2007-04-05T22:00 45")
        self.assertEqual(dict(evaluate(stream)), {"h": "keep"})

    def test_invalid_inputs(self):
        invalid = [
            "", "reference 70 45", "reference 70 101", "reference 70 NaN",
            "reference 70 45\nhumidity h", "reference 70 45\nnoise n",
            "reference 70 45\n2007-04-05T22:00 45",
            "reference 70 45\nreference 70 45",
            "reference 70 45\nhumidity h\n2007-02-30T22:00 45",
            "reference 70 45\nhumidity h\n2007-04-05T22:00 NaN",
            "reference 70 45\nhumidity h\n2007-04-05T22:00 inf",
            "reference 70 45\nhumidity h extra",
            "reference 70 45\nhumidity h\n2007-04-05T22:00 45 extra",
            "reference 70 45\nhumidity h\n2007-04-05T22:00 45\nhumidity h",
            "x" * (MAX_LINE_LENGTH + 1),
        ]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(InputError):
                list(evaluate(io.StringIO(text)))

    def test_numeric_limits(self):
        for token in ("1e1000000", "1e-1000000", "1000000000001",
                      "46.00000000000000000000000000001", "1e1000"):
            with self.subTest(token=token), self.assertRaises(InputError):
                number(token, 1)
        for token in ("1e12", "-1e12", "1e-16", "46.0000000000001"):
            with self.subTest(token=token):
                self.assertEqual(number(token, 1), Decimal(token))

    def test_timestamp_is_validated_but_order_does_not_matter(self):
        text = "reference 70 45\nhumidity h\n2007-04-05T22:02:01Z 45\n2007-04-05T22:00:01.123+02:00 44\n"
        self.assertEqual(dict(evaluate(io.StringIO(text))), {"h": "keep"})

    def test_late_bad_reading_still_validated_after_humidity_discard(self):
        text = "reference 70 45\nhumidity h\n2007-04-05T22:00 40\n2007-04-05T22:01 bad\n"
        with self.assertRaises(InputError):
            list(evaluate(io.StringIO(text)))

    def test_parser_never_uses_unbounded_read(self):
        class BoundedStream(io.StringIO):
            def read(self, *args):
                raise AssertionError("unbounded read")
            def readline(self, size=-1):
                if size != MAX_LINE_LENGTH + 1:
                    raise AssertionError("unbounded readline")
                return super().readline(size)
        self.assertEqual(dict(evaluate(BoundedStream(
            "reference 70 45\nhumidity h\n2007-04-05T22:00 45\n"
        ))), {"h": "keep"})


class CLITests(unittest.TestCase):
    def test_module_invocation_and_structured_summary(self):
        process = subprocess.run([sys.executable, "-m", "sensor_qc", "--input",
                                  str(ROOT / "examples/sample.log")],
                                 check=False, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), json.loads(
            (ROOT / "examples/expected.json").read_text()))
        self.assertEqual(json.loads(process.stderr)["event"], "evaluation_completed")

    def test_stdin(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
             mock.patch("sys.stdin", io.StringIO(
                 "reference 70 45\nhumidity h\n2007-04-05T22:00 45\n")):
            self.assertEqual(run([]), 0)
        self.assertEqual(json.loads(out.getvalue()), {"h": "keep"})

    def test_invalid_input_preserves_existing_output_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "in.log", Path(folder) / "out.json"
            source.write_text("reference 70 45\nhumidity h\n2007-04-05T22:00 45\nhumidity empty\n")
            output.write_text("existing result")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run(["--input", str(source), "--output", str(output)]), 2)
            self.assertEqual(output.read_text(), "existing result")
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["in.log", "out.json"])

    def test_invalid_input_emits_no_partial_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "in.log"
            source.write_text("reference 70 45\nhumidity h\n2007-04-05T22:00 45\nhumidity empty\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run(["--input", str(source)]), 2)
            self.assertEqual(out.getvalue(), "")

    def test_atomic_success_and_same_input_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "data"
            source.write_text("reference 70 45\nhumidity h\n2007-04-05T22:00 45\n")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run(["--input", str(source), "--output", str(source)]), 0)
            self.assertEqual(json.loads(source.read_text()), {"h": "keep"})

    def test_extreme_number_is_reported_as_invalid_input(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
             mock.patch("sys.stdin", io.StringIO(
                 "reference 70 45\nhumidity h\n2007-04-05T22:00 1e1000000\n")):
            self.assertEqual(run([]), 2)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(json.loads(err.getvalue())["kind"], "invalid_input")

    def test_replace_failure_preserves_output_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "in.log", Path(folder) / "out.json"
            source.write_text("reference 70 45\nhumidity h\n2007-04-05T22:00 45\n")
            output.write_text("previous result")
            with mock.patch("sensor_qc.cli.os.replace", side_effect=OSError("replace failed")), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run(["--input", str(source), "--output", str(output)]), 1)
            self.assertEqual(output.read_text(), "previous result")
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()),
                             ["in.log", "out.json"])

    def test_missing_file_exit_one(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run(["--input", "/nonexistent/qc/input.log"]), 1)


class PackagingTests(unittest.TestCase):
    def test_repeat_packaging_excludes_destination_and_mac_metadata(self):
        import shutil
        import zipfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            shutil.copyfile(ROOT / "scripts/package.py", root / "scripts/package.py")
            (root / "sample.txt").write_text("sample")
            (root / "._sample.txt").write_text("metadata")
            (root / ".DS_Store").write_text("metadata")
            for _ in range(2):
                process = subprocess.run([sys.executable, "scripts/package.py"],
                                         cwd=root, text=True, capture_output=True)
                self.assertEqual(process.returncode, 0, process.stderr)
                with zipfile.ZipFile(root / "sensor-qc.zip") as archive:
                    names = [Path(name).name for name in archive.namelist()]
                    self.assertEqual(sorted(names), ["package.py", "sample.txt"])


if __name__ == "__main__":
    unittest.main()
