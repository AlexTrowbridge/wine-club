# Wine Club

Web app for the institute wine club: members, sessions, wines, scores and the
statistics that used to live in `Wine Club.xlsx`. Django + HTMX + PostgreSQL,
shipped as one container and deployed to Kubernetes with Kustomize.

## Features

- **Live scoring**: an organiser opens a session; members score each bottle on their
  phone (`/sessions/<n>/score/`). Scores stay hidden, including from stats, until
  the organiser reveals or closes the session.
- **Score grid**: organisers can enter or correct anyone's score in a spreadsheet-like
  grid on the session page (number, `x` = tasted but not scored, blank = remove).
- Wines (filter and sort), members, attendance, leaderboards, and analysis by varietal,
  vintage, region, country, age, price band, style and purchaser. Also a rating-vs-price
  log fit and a purchaser × rater matrix.
- `import_workbook` loads the legacy spreadsheet, from a file or a Box shared link.
  `export_workbook` (or *Attendance → Download*) writes the same layout back out.
- **Import from Box**: save the workbook's Box shared link under *Admin → Workbook
  import*, then click *Import now* to pull the latest version. Records are added and
  updated, never deleted, and sessions open in the app keep their status. If anything
  fails (download, layout, or a clash with data entered in the app), nothing changes.
  The page shows the last import's report.
- Django admin (`/admin/`) handles detailed edits: wine details and varietals, linking
  logins to members, regions, and so on.

Roles: anyone logged in can view. Members score their own wines while a session is
open. Users in the **Organiser** group (or superusers) manage sessions and bottles and
can edit any score.

## Local development

```sh
python3 -m venv .venv && .venv/bin/pip install uv
UV_PROJECT_ENVIRONMENT=.venv .venv/bin/uv sync
echo DEBUG=true > .env                       # SQLite db.sqlite3, dev secret key
.venv/bin/python manage.py migrate
.venv/bin/python manage.py import_workbook "Wine Club.xlsx"   # writes import_review.csv
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
.venv/bin/python -m pytest                   # TEST_DATABASE_URL=postgres://... to test on Postgres
```

Or use `docker compose up --build` (or `podman compose`) for app + Postgres.
The compose file's header has the import commands.

`Wine Club.xlsx` contains members' personal data and is git-ignored. Don't commit it.

### Import notes

The importer fixes three known date typos in the workbook (see `DATE_CORRECTIONS` in
`club/importer.py`). It splits names like *"Henschke 2020 Henry's Seven Shiraz Grenache
Mataro Viognier"* into producer, vintage, label and varietals (`club/naming.py`). Anything
it can't resolve goes into `import_review.csv`. It also reports where the sheet
disagrees with itself: hand-typed ages that don't match vintage vs date, and members
who scored without being marked present.

## Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | e.g. `postgres://user:pass@host:5432/db` (SQLite if unset) |
| `SECRET_KEY` | required unless `DEBUG=true` |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | comma-separated |
| `SECURE_PROXY_SSL` | `true` behind a TLS-terminating ingress |
| `EMAIL_URL`, `DEFAULT_FROM_EMAIL` | for password-reset mail (console by default) |
| `ADMIN_PASSWORD` | password for the default superuser; `manage.py ensure_admin` creates it if missing (skipped when unset) |
| `ADMIN_USERNAME` | default superuser's name (default `admin`) |
| `WEB_CONCURRENCY` | gunicorn workers (default 3) |

Health endpoints: `/healthz` (process) and `/readyz` (database). Neither needs a login.

## Kubernetes

```sh
podman build -t ghcr.io/alextrowbridge/wine-club:0.1.0 . && podman push ...
cp deploy/overlays/prod/secrets.env.example deploy/overlays/prod/secrets.env  # fill in
# edit hostname / image tag / storage class in deploy/overlays/prod/kustomization.yaml
kubectl apply -k deploy/overlays/prod
```

This creates the namespace `wine-club` with:

- the app Deployment (2 replicas, migrations run in an initContainer, read-only root
  filesystem, non-root)
- a Service and an Ingress (TLS via a cert-manager annotation)
- a Postgres 17 StatefulSet
- a nightly `pg_dump` CronJob that keeps 30 days of dumps on its own PVC

The migrate initContainer also runs `ensure_admin`, so with `ADMIN_PASSWORD` in
`secrets.env` the first deploy creates the superuser `admin`. It never resets an
existing user's password, so change it in the app after first login.

First-time setup:

```sh
POD=$(kubectl -n wine-club get pod -l app.kubernetes.io/name=wine-club -o name | head -1)
kubectl -n wine-club cp "Wine Club.xlsx" ${POD#pod/}:/tmp/club.xlsx
kubectl -n wine-club exec $POD -- python manage.py import_workbook /tmp/club.xlsx --review-csv /tmp/review.csv
```

Test a backup: `kubectl -n wine-club create job --from=cronjob/pg-backup backup-test`.
Restore: `gunzip -c dump.sql.gz | psql -h postgres -U wineclub wineclub`.
