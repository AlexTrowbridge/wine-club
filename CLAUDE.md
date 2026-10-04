# Wine Club

Django + HTMX app (PostgreSQL) for the institute wine club, deployed as a container to a
small k8s cluster with Kustomize. See README.md for setup and deployment.

## Releasing: required on every git push

Whenever you perform a `git push`, run `./release.sh` immediately afterwards to build and
publish the container image to ghcr.io (`ghcr.io/alextrowbridge/wine-club`).

- Push first: the script refuses to publish a commit that isn't on origin, or a dirty tree.
- It runs lint + tests, builds for linux/amd64 and pushes tags `sha-<commit>`, `<version>`
  (from `pyproject.toml`) and `latest`.
- If `<version>` is already published from a different commit, the script stops. Ask the
  user whether to bump `version` in `pyproject.toml`; don't bump it unasked.
- If it fails for lack of the `write:packages` scope, tell the user to run
  `gh auth refresh -h github.com -s write:packages`. Don't work around authentication.
- Report the published tags. Remind the user to update `newTag` in
  `deploy/overlays/prod/kustomization.yaml` if they want to deploy that version.
- If nothing that goes into the image changed since the published `:latest` (only
  tests, docs, `deploy/`, i.e. paths excluded by `.dockerignore`), the script reports
  that and exits successfully without publishing. That's the expected outcome, not an
  error: don't bump the version or pass `--force` to get around it. Use `--force` only
  when the user asks.
- `./release.sh --dry-run` builds without pushing (useful for checking the Dockerfile).

Git auth: if a plain `git push` fails for lack of credentials, use
`git -c 'credential.helper=!gh auth git-credential' push ...`. Don't change the git config.

## Commands

```sh
.venv/bin/python -m pytest -q                 # tests (SQLite; TEST_DATABASE_URL=postgres://... for Postgres)
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/python manage.py runserver          # needs .env with DEBUG=true
.venv/bin/python manage.py import_workbook "Wine Club.xlsx"
.venv/bin/python manage.py makemigrations --check --dry-run
```

Dependencies are managed with uv (`UV_PROJECT_ENVIRONMENT=.venv .venv/bin/uv sync`). Keep
`uv.lock` committed.

## Layout and conventions

- `club/models.py`: Member, Era, Session, Attendance, Country/Region, Varietal, Wine (+ WineVarietal),
  Tasting (one bottle at one session), Rating (`score` NULL = tasted, not scored).
- `club/stats.py`: all statistics, computed in Python from `stats.bottles()`. Wine-level
  figures use each bottle's average score, and stdev is population stdev (matches the old
  spreadsheet). Always go through `.visible()` querysets, so scores from an open,
  unrevealed session never leak into pages or stats.
- `club/naming.py`: parses "Producer Vintage Label Varietals" names. Add new grapes and
  aliases to `VARIETALS`.
- `club/importer.py` / `club/exporter.py`: legacy workbook import and export. They must
  round-trip (covered by `tests/test_pages.py::test_export_round_trips`).
- Permissions live in `club/permissions.py` (Organiser group). All views require login
  except those marked `@login_not_required` (health checks).
- Front-end libraries are vendored in `club/static/club/vendor/`. Strip `sourceMappingURL`
  comments from vendored files, or `collectstatic` fails in the image build.
- The container runs non-root with a read-only root filesystem (only `/tmp` is writable),
  and gunicorn uses gthread workers. Keep new code compatible with that.

## Data privacy

`Wine Club.xlsx`, `import_review.csv`, `.env`, `db.sqlite3` and
`deploy/overlays/*/secrets.env` hold personal data or secrets. They're git-ignored and must
never be committed or baked into the image (see `.dockerignore`).
