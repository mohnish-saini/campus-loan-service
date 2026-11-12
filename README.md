# Campus Loan Service

Scalable Services assignment by Mohnish Saini, 2025MT03144.

This service records equipment borrowing and returns. It calls the [Equipment Service](https://github.com/mohnish-saini/campus-equipment-service) through REST to reserve or release an item. Each service has its own PostgreSQL database.

## Run locally

Start the Equipment Service first. The [Equipment README](https://github.com/mohnish-saini/campus-equipment-service#run-the-application-with-docker) includes the commands to clone and run both repositories.

From this repository's folder, start Loan and its database with:

```bash
docker compose up --build -d
```

The API page is http://localhost:8002/docs. The Compose file expects Equipment on http://host.docker.internal:8001 through Docker Desktop.

For a manual container configuration, `DATABASE_URL` sets the Loan PostgreSQL connection and `EQUIPMENT_SERVICE_URL` sets the Equipment API address. In Minikube, the Equipment address is `http://equipment-service:8000`.

## Loan endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/loans` | Borrow an item |
| GET | `/loans` | List loans; optionally filter by borrower_id |
| GET | `/loans/{loan_id}` | Check a loan |
| POST | `/loans/{loan_id}/return` | Return the borrowed item |
| GET | `/health/live` | Check the API process |
| GET | `/health/ready` | Check the database connection |

A borrowing request contains a new UUID, the equipment ID and the borrower ID:

```json
{
  "loan_id": "e1df5bc8-246b-4d09-bbda-3b3524fe7cc0",
  "equipment_id": "<ID returned when equipment is registered>",
  "borrower_id": "2025MT03144"
}
```

Use a new loan ID for each new borrowing request. To retry a request, keep the same ID and payload. The service saves a PENDING record before calling Equipment. It becomes ACTIVE when the reservation succeeds, or REJECTED when Equipment refuses it. If Equipment is unreachable, the API returns 503 and the request can be retried. Returned loans have status RETURNED. Repeating a return does not release another unit.

## Run the Loan tests

```bash
docker build --target test -t campus-loan-test .
docker run --rm campus-loan-test
```

The tests use SQLite and replace the Equipment HTTP call with a mock. They check retrying after a timeout, rejected requests and repeated returns.

To check both running services with real PostgreSQL, run the integration script from this folder using Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python tests/integration_check.py
```

The default URLs are http://localhost:8001 and http://localhost:8002. For Minikube port-forwards, run:

```bash
EQUIPMENT_URL=http://localhost:8101 LOAN_URL=http://localhost:8102 python tests/integration_check.py
```

The script checks the full workflow, including eight requests competing for one unit and six retries of the same request. It saves the results in `integration-results.json`.

## Test with Postman

Import `postman/CampusEquipmentLending.postman_collection.json` into Postman. The collection defaults to the Minikube ports 8101 and 8102. For Docker Compose, change `equipment_url` to `http://localhost:8001` and `loan_url` to `http://localhost:8002` in the collection variables.

Run requests 01 to 13 in order. They register a camera, borrow it, repeat the request, check stock, reject a second borrower and return the camera. Requests 07 and 12 intentionally expect 409 and 422. A full collection run has 17 assertions.

## Deploy to Minikube

Follow the [Minikube steps in the Equipment README](https://github.com/mohnish-saini/campus-equipment-service#deploy-both-services-to-minikube). After building and loading both images, this service's resources can be applied separately:

```bash
kubectl --context campus-lending apply -f k8s.yaml
```

## Files

- `app/main.py`: Loan model, request models and routes.
- `tests/test_loans.py`: independent Loan tests.
- `tests/integration_check.py`: checks against both running services.
- `postman/`: collection for the borrowing and return workflow.
- `requirements.txt`: API dependencies.
- `requirements-dev.txt`: test dependencies.
- `Dockerfile`: application image and optional test target.
- `compose.yaml`: Loan API and database for local Docker testing.
- `k8s.yaml`: Loan deployment for Minikube.

Login, borrower verification and automatic recovery of abandoned PENDING loans are not included. The passwords in the deployment files are local demo values. This is a local assignment setup, not a production deployment.
