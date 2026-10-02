#!/usr/bin/env bash

set -euo pipefail
chart=helm/sensor-qc
helm lint "$chart" --strict
helm template demo "$chart" >/dev/null
helm template production "$chart" -f examples/values-pvc.yaml >/dev/null
for mode in input output; do
  if helm template invalid "$chart" --set "$mode.mode=pvc" >/dev/null 2>&1; then
    echo "ERROR: missing $mode PVC was not rejected" >&2
    exit 1
  fi
done
if helm template invalid "$chart" --set input.mode=unknown >/dev/null 2>&1; then
  echo "ERROR: unknown input mode was not rejected" >&2
  exit 1
fi
if helm template invalid "$chart" --set input.file=../escape.log >/dev/null 2>&1; then
  echo "ERROR: unsafe input filename was not rejected" >&2
  exit 1
fi
