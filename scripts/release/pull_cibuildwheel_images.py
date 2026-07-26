"""Pre-pull cibuildwheel's pinned Linux images with bounded retries."""

from __future__ import annotations

import argparse
import configparser
import importlib.resources
import platform
import subprocess
import time
from collections.abc import Sequence

_IMAGE_NAMES = ("manylinux_2_28", "musllinux_1_2")
_ARCHITECTURES = {
    "amd64": "x86_64",
    "arm64": "aarch64",
    "x86_64": "x86_64",
    "aarch64": "aarch64",
}
_MAX_ATTEMPTS = 3


def _parse_pinned_images(config: str, machine: str) -> tuple[str, ...]:
    try:
        architecture = _ARCHITECTURES[machine.lower()]
    except KeyError as error:
        raise RuntimeError(f"unsupported Linux build architecture: {machine}") from error

    parser = configparser.ConfigParser(inline_comment_prefixes=("#",))
    parser.read_string(config)
    try:
        return tuple(parser[architecture][name] for name in _IMAGE_NAMES)
    except KeyError as error:
        raise RuntimeError(
            f"cibuildwheel does not define the expected images for {architecture}"
        ) from error


def _pinned_images() -> tuple[str, ...]:
    resource = (
        importlib.resources.files("cibuildwheel")
        .joinpath("resources")
        .joinpath("pinned_docker_images.cfg")
    )
    return _parse_pinned_images(resource.read_text(encoding="utf-8"), platform.machine())


def _pull_with_retry(image: str) -> None:
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        result = subprocess.run(["docker", "pull", image], check=False)
        if result.returncode == 0:
            return
        if attempt == _MAX_ATTEMPTS:
            raise RuntimeError(f"failed to pull {image} after {_MAX_ATTEMPTS} attempts")
        delay = attempt * 10
        print(
            f"docker pull attempt {attempt} failed for {image}; retrying in {delay}s",
            flush=True,
        )
        time.sleep(delay)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the resolved image references without pulling them",
    )
    args = parser.parse_args(argv)

    images = _pinned_images()
    for image in images:
        print(image, flush=True)
        if not args.dry_run:
            _pull_with_retry(image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
