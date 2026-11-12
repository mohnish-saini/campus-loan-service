# Campus Loan Service

Mohnish Saini — 2025MT03144 — Scalable Services individual assignment.

This service has its own repository, Docker image, database and independent tests.
Python 3.12, FastAPI, SQLAlchemy and PostgreSQL 16.

## Build and test independently

```bash
docker build -t campus-loan:1.0 .
docker run --rm -v "$PWD/tests:/srv/tests:ro" campus-loan:1.0 python -m pytest -q -p no:cacheprovider
```

Tests use temporary SQLite databases and a mocked HTTP dependency for Loan. The full submission additionally includes real PostgreSQL integration and concurrency checks.

## Run

Set DATABASE_URL to a PostgreSQL URL such as `postgresql+psycopg://USER:PASSWORD@DATABASE_HOST/DATABASE_NAME`. Loan also needs EQUIPMENT_SERVICE_URL (default `http://equipment-service:8000`).

```bash
docker run --rm -p 8000:8000 --env-file .env campus-loan:1.0
```

Create .env locally. Never commit real credentials. Swagger UI: /docs. Liveness: /health/live. Database readiness: /health/ready.

## Structure

- app/main.py: API routes, models and lifecycle logic.
- tests/: independent service tests.
- requirements.txt: pinned direct dependencies.
- Dockerfile: non-root container image.
- cluster-example.json: full local Minikube example; build and load both service images before applying.

## Collaboration

Equipment owns inventory and reservations. Loan owns borrowing records and calls Equipment over REST; neither service accesses the other's database. UUID loan IDs identify idempotent requests. PostgreSQL row locks prevent over-allocation. Loan persists PENDING intent before calling Equipment, allowing a timed-out request to recover on replay with the same ID. Returns are idempotent. A background reconciliation worker is not implemented.

Companion repositories:
- https://github.com/mohnish-saini/campus-equipment-service
- https://github.com/mohnish-saini/campus-loan-service

The full submission includes deployment scripts, Postman collection, architecture and evidence. This is a local academic demonstration without authentication. Production needs identity checks, protected internal endpoints, managed credentials, migrations and database backups. Manifest passwords are local examples.
