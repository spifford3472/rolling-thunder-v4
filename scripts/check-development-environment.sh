#!/usr/bin/env bash

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "===== ROLLING THUNDER DEVELOPMENT ENVIRONMENT ====="
echo "Project: $PROJECT_ROOT"
echo

echo "===== SYSTEM ====="
hostnamectl --static
uname -m
echo

echo "===== GIT ====="
git status --short
git branch --show-current
git remote -v
echo

echo "===== PYTHON ====="
python --version
which python
echo

echo "===== DEVELOPMENT TOOLS ====="
pytest --version
ruff --version
mypy --version
echo

echo "===== PACKAGE IMPORT ====="
python -c 'import rolling_thunder; print(rolling_thunder.__file__)'
echo

echo "===== SERIAL DEVICES ====="
ls -l /dev/serial/by-id 2>/dev/null || echo "No persistent serial devices detected."
echo

echo "===== AUDIO CAPTURE DEVICES ====="
arecord -l 2>/dev/null || echo "No audio capture devices detected."
echo

echo "===== BLUETOOTH ====="
systemctl is-active bluetooth
echo

echo "===== COMPLETE ====="
