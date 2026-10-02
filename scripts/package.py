"""Build and verify a source archive without caches, virtualenvs, or git metadata."""
import tempfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = root / "sensor-qc.zip"
excluded = {"__pycache__", ".git", ".venv", "build", "dist"}
paths = sorted(p for p in root.rglob("*") if p.is_file()
               and not any(part in excluded or part.endswith(".egg-info")
                           for part in p.relative_to(root).parts)
               and p != destination
               and not p.name.startswith("._")
               and p.name not in {"results.json", "rendered.yaml", ".DS_Store"}
               and p.suffix not in {".pyc", ".tgz"})

with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in paths:
        archive.write(path, Path(root.name) / path.relative_to(root))

with zipfile.ZipFile(destination) as archive, tempfile.TemporaryDirectory() as folder:
    assert archive.testzip() is None
    archive.extractall(folder)
    for path in paths:
        restored = Path(folder) / root.name / path.relative_to(root)
        assert restored.read_bytes() == path.read_bytes(), path

print(f"Verified {len(paths)} files: {destination}")
