#!/usr/bin/env bash
# Build the wine-club container image and publish it to GitHub Container Registry.
#
# Usage: ./release.sh [--dry-run]
#
# Tags pushed (IMAGE defaults to ghcr.io/alextrowbridge/wine-club):
#   IMAGE:sha-<short commit>   always; immutable, identifies exactly what was built
#   IMAGE:<version>            from pyproject.toml; refused if it already exists with
#                              different content (bump the version to release a change)
#   IMAGE:latest
#
# Requirements: podman or docker, gh logged in with the write:packages scope
#   (gh auth refresh -h github.com -s write:packages), a clean working tree, and
#   HEAD pushed to origin. Runs ruff + pytest first unless SKIP_TESTS=1.
#
# Environment overrides: IMAGE, PLATFORM (default linux/amd64), ENGINE, SKIP_TESTS.
set -euo pipefail

cd "$(dirname "$0")"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

REPO_URL="https://github.com/AlexTrowbridge/wine-club"
IMAGE="${IMAGE:-ghcr.io/alextrowbridge/wine-club}"
PLATFORM="${PLATFORM:-linux/amd64}"
REGISTRY="${IMAGE%%/*}"

die() { echo "release: $*" >&2; exit 1; }
step() { echo "==> $*"; }

ENGINE="${ENGINE:-$(command -v podman || command -v docker || true)}"
[[ -n "$ENGINE" ]] || die "neither podman nor docker is installed"

# --- Preconditions --------------------------------------------------------------

if [[ -n "$(git status --porcelain)" ]]; then
  [[ "$DRY_RUN" == 1 ]] || die "working tree has uncommitted changes; commit them so the image matches a commit"
  echo "release: warning: uncommitted changes (allowed for --dry-run only)" >&2
fi

COMMIT="$(git rev-parse HEAD)"
SHORT="$(git rev-parse --short=7 HEAD)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
[[ -n "$VERSION" ]] || die "could not read version from pyproject.toml"

if [[ "$DRY_RUN" == 0 ]]; then
  git fetch --quiet origin 2>/dev/null || true
  git branch -r --contains "$COMMIT" | grep -q . \
    || die "commit $SHORT is not on origin; git push first"

  command -v gh >/dev/null || die "gh is not installed"
  gh auth status -h github.com 2>&1 | grep -q "write:packages" \
    || die "gh token lacks the write:packages scope; run: gh auth refresh -h github.com -s write:packages"

  # Never move a version tag to different code: if IMAGE:VERSION is already published,
  # it must be from this same commit (i.e. also tagged sha-SHORT).
  published_tags="$(gh api --paginate "/user/packages/container/${IMAGE##*/}/versions" \
    -q '.[].metadata.container.tags | join(",")' 2>/dev/null || true)"
  version_line="$(grep -E "(^|,)${VERSION//./\\.}(,|$)" <<<"$published_tags" || true)"
  if [[ -n "$version_line" && ",$version_line," != *",sha-$SHORT,"* ]]; then
    die "$IMAGE:$VERSION is already published from another commit ($version_line); bump the version in pyproject.toml"
  fi
fi

# --- Checks ------------------------------------------------------------------------

if [[ "${SKIP_TESTS:-0}" != 1 ]]; then
  [[ -x .venv/bin/python ]] || die ".venv not found (see README), or set SKIP_TESTS=1"
  step "Lint and tests"
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/python -m pytest -q
fi

# --- Build -------------------------------------------------------------------------

step "Building $IMAGE:sha-$SHORT ($PLATFORM, $(basename "$ENGINE"))"
"$ENGINE" build \
  --platform "$PLATFORM" \
  --label "org.opencontainers.image.source=$REPO_URL" \
  --label "org.opencontainers.image.revision=$COMMIT" \
  --label "org.opencontainers.image.version=$VERSION" \
  --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  -t "$IMAGE:sha-$SHORT" \
  -t "$IMAGE:$VERSION" \
  -t "$IMAGE:latest" \
  .

if [[ "$DRY_RUN" == 1 ]]; then
  step "Dry run: built $IMAGE:{sha-$SHORT,$VERSION,latest}; nothing pushed"
  exit 0
fi

# --- Publish -----------------------------------------------------------------------

step "Logging in to $REGISTRY"
gh auth token | "$ENGINE" login "$REGISTRY" -u "$(gh api user -q .login)" --password-stdin >/dev/null

for tag in "sha-$SHORT" "$VERSION" latest; do
  step "Pushing $IMAGE:$tag"
  "$ENGINE" push "$IMAGE:$tag"
done

step "Published $IMAGE:$VERSION (sha-$SHORT)"
echo "Deploy: set newTag: \"$VERSION\" (or sha-$SHORT) in deploy/overlays/prod/kustomization.yaml"
