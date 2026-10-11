#!/usr/bin/env bash
# Non-root offline build candidate. Separate root review/copy/install required.
set -euo pipefail
if [[ $# != 4 ]]; then
  echo 'USAGE: stage-forge-voacap-baseline.sh REPO_PATH EXACT_40_CHAR_SHA DEPENDENCY_WHEELHOUSE DEST_DIR' >&2
  exit 2
fi
REPO=$1
SHA=$2
DEPENDENCY_WHEELHOUSE=$3
DEST=$4
[[ $SHA =~ ^[0-9a-f]{40}$ ]] || { echo 'ERROR: invalid SHA' >&2; exit 3; }
[[ $DEST == /* && $DEPENDENCY_WHEELHOUSE == /* ]] || { echo 'ERROR: absolute paths required' >&2; exit 3; }
[[ -d $DEPENDENCY_WHEELHOUSE && ! -e $DEST ]] || { echo 'ERROR: dependency wheelhouse missing or dest exists' >&2; exit 3; }
git -C "$REPO" cat-file -e "$SHA^{commit}"
git -C "$REPO" branch -r --contains "$SHA" | grep -Eq '^[[:space:]]*origin/' || {
  echo 'ERROR: target SHA must exist in a fetched origin branch' >&2
  exit 3
}
TEMP=$(mktemp -d)
trap 'rm -rf "$TEMP"' EXIT
mkdir -m 0700 "$TEMP/src"
git -C "$REPO" archive "$SHA" | tar -x -C "$TEMP/src"
VERSION=$(python3 - "$TEMP/src/pyproject.toml" <<'PY'
import sys,tomllib
with open(sys.argv[1], 'rb') as handle:
    version=tomllib.load(handle)['project']['version']
assert version.count('.')==2 and all(part.isdigit() for part in version.split('.'))
print(version)
PY
)
mkdir -m 0700 "$DEST"
mkdir -m 0700 "$DEST/wheelhouse"
find "$DEPENDENCY_WHEELHOUSE" -maxdepth 1 -type f -name '*.whl' ! -name 'rolling_thunder-*.whl' -exec cp '{}' "$DEST/wheelhouse/" ';'
"${BUILD_PYTHON:-$REPO/.venv/bin/python}" -m pip wheel --no-index --no-deps --no-build-isolation --wheel-dir "$DEST/wheelhouse" "$TEMP/src"
[[ -f "$DEST/wheelhouse/rolling_thunder-${VERSION}-py3-none-any.whl" ]] || { echo 'ERROR: app wheel missing' >&2; exit 5; }
cp "$TEMP/src/deploy/systemd/rolling-thunder-forge-voacap-baseline.service" "$DEST/"
cp "$TEMP/src/deploy/systemd/rolling-thunder-forge-voacap-baseline.timer" "$DEST/"
printf '%s\n' "$SHA" > "$DEST/COMMIT_SHA"
printf 'forge-voacap-baseline\n' > "$DEST/COMPONENT"
printf '%s\n' "$VERSION" > "$DEST/PROJECT_VERSION"
(cd "$DEST/wheelhouse" && sha256sum ./*.whl > SHA256SUMS)
chmod -R go-rwx "$DEST"
echo "CANDIDATE_READY=$DEST"
echo "SHA=$SHA"
echo 'NEXT: ADMIN REVIEWS, COPIES TO ROOT-OWNED 0700 STAGE, CONFIGURES OFF GATES, INSTALLS BASELINE-ONLY HELPER'
