"""Create a reproducible static ICGEM subset for package distribution.

The source may be a plain ``.gfc`` file or an archive containing one. Header
metadata and coefficient text are preserved; only the declared maximum degree
and coefficient rows beyond the requested truncation are changed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def open_icgem_source(path: Path) -> Iterator[TextIO]:
    if path.suffix.lower() != ".zip":
        with path.open("r", encoding="utf-8", errors="strict", newline="") as stream:
            yield stream
        return

    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if name.lower().endswith(".gfc")]
        if len(candidates) != 1:
            raise ValueError(
                f"expected exactly one .gfc member in {path}, found {len(candidates)}"
            )
        with archive.open(candidates[0]) as binary_stream:
            with io.TextIOWrapper(binary_stream, encoding="utf-8", errors="strict") as stream:
                yield stream


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def truncate_icgem(source: Path, output: Path, max_degree: int) -> tuple[int, int]:
    if max_degree < 2:
        raise ValueError("max_degree must be at least 2")
    output.parent.mkdir(parents=True, exist_ok=True)
    header_complete = False
    max_degree_header_seen = False
    coefficient_count = 0
    largest_degree = -1

    temporary_path: Path | None = None
    try:
        with open_icgem_source(source) as input_stream:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                for raw_line in input_stream:
                    line = raw_line.rstrip("\r\n")
                    stripped = line.strip()
                    if not header_complete:
                        parts = stripped.split()
                        if parts and parts[0].lower() == "max_degree":
                            line = f"max_degree {max_degree}"
                            max_degree_header_seen = True
                        temporary.write(line + "\n")
                        if parts and parts[0].lower() == "end_of_head":
                            header_complete = True
                        continue

                    if not stripped or stripped.startswith(("#", "%")):
                        temporary.write(line + "\n")
                        continue
                    parts = stripped.split()
                    record = parts[0].lower()
                    if record in {"gfct", "trnd", "asin", "acos"}:
                        raise ValueError("the packaging helper accepts static gfc records only")
                    if record != "gfc" or len(parts) < 5:
                        continue
                    degree = int(parts[1])
                    if degree <= max_degree:
                        temporary.write(line + "\n")
                        coefficient_count += 1
                        largest_degree = max(largest_degree, degree)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise

    if not header_complete or not max_degree_header_seen:
        assert temporary_path is not None
        temporary_path.unlink(missing_ok=True)
        raise ValueError("invalid ICGEM header")
    if largest_degree != max_degree:
        assert temporary_path is not None
        temporary_path.unlink(missing_ok=True)
        raise ValueError(
            f"source does not contain requested degree {max_degree}; largest was {largest_degree}"
        )
    assert temporary_path is not None
    temporary_path.replace(output)
    return coefficient_count, largest_degree


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="full ICGEM .gfc file or ZIP archive")
    parser.add_argument("output", type=Path, help="destination .gfc subset")
    parser.add_argument("--max-degree", type=int, default=120)
    arguments = parser.parse_args()

    count, degree = truncate_icgem(arguments.source, arguments.output, arguments.max_degree)
    sidecar = arguments.output.with_suffix(".sha256")
    sidecar.write_text(
        f"{sha256(arguments.output)}  {arguments.output.name}\n",
        encoding="ascii",
    )
    print(f"wrote {arguments.output} with {count} coefficients through degree {degree}")
    print(f"source sha256: {sha256(arguments.source)}")
    print(f"output sha256: {sha256(arguments.output)}")


if __name__ == "__main__":
    main()
