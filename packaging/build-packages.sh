#!/bin/bash
# SPDX-License-Identifier: MIT
#
# Build the release artifacts: the Debian package pshx500_<version>_all.deb
# and the Python wheel pshx500-<version>-py3-none-any.whl.
#
#   packaging/build-packages.sh <version> [<output dir>]
#
# <version> must match the version in pyproject.toml and pshx500/__init__.py.
# Needs python3 with pip and numpy/libusb1 (for the tests) and nfpm. Used by
# the workflows; runs the same way locally.
set -euo pipefail

VERSION=${1:?usage: $0 <version> [<output dir>]}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(realpath -m "${2:-$ROOT/dist}")
WORK=$ROOT/build-pkg

die() { echo "build-packages: $*" >&2; exit 1; }

# ---- versions must agree ----
py_ver=$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml")
mod_ver=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/pshx500/__init__.py")
[ "$py_ver" = "$VERSION" ] || die "pyproject.toml has $py_ver, not $VERSION"
[ "$mod_ver" = "$VERSION" ] || die "pshx500/__init__.py has $mod_ver, not $VERSION"

cd "$ROOT"
python3 -m unittest discover -s tests -v

rm -rf "$WORK"
mkdir -p "$WORK" "$OUT"

# ---- wheel ----
python3 -m pip wheel --no-deps --no-build-isolation -w "$OUT" "$ROOT"
rm -rf "$ROOT/build" "$ROOT"/*.egg-info

# ---- Debian package ----
STAGE=$WORK/stage
mkdir -p "$STAGE"
cp -r "$ROOT/pshx500" "$STAGE/"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$STAGE" -type d -exec chmod 0755 {} +
find "$STAGE" -type f -exec chmod 0644 {} +

sed -e "s|@VERSION@|$VERSION|g" -e "s|@STAGE@|$STAGE|g" \
	"$ROOT/packaging/nfpm.yaml" > "$WORK/nfpm.yaml"
nfpm package -f "$WORK/nfpm.yaml" -p deb -t "$OUT/"

rm -rf "$WORK"
ls -l "$OUT"
