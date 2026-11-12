"""Black-box integration checks against real PostgreSQL-backed HTTP services."""
import concurrent.futures
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import httpx

E = os.getenv("EQUIPMENT_URL", "http://localhost:8001")
L = os.getenv("LOAN_URL", "http://localhost:8002")
records = []


def call(method, url, expected, **kwargs):
    response = httpx.request(method, url, timeout=20, **kwargs)
    assert response.status_code == expected, (url, response.status_code, response.text)
    records.append(
        {
            "method": method,
            "url": url,
            "request": kwargs.get("json"),
            "status": response.status_code,
            "response": response.json(),
        }
    )
    return response.json()


for url in [E, L]:
    call("GET", url + "/health/ready", 200)
item = call(
    "POST",
    E + "/equipment",
    201,
    json={"name": "Demo DSLR Camera", "category": "Photography", "total_quantity": 1},
)
request = {
    "loan_id": str(uuid4()),
    "equipment_id": item["id"],
    "borrower_id": "2025MT03144",
}
loan = call("POST", L + "/loans", 201, json=request)
assert loan["status"] == "ACTIVE"
assert call("POST", L + "/loans", 201, json=request)["id"] == loan["id"]
assert call("GET", E + "/equipment/" + item["id"], 200)["available_quantity"] == 0
call("POST", L + "/loans", 409, json={**request, "loan_id": str(uuid4())})
call("POST", L + "/loans", 409, json={**request, "borrower_id": "another-borrower"})
assert call("POST", L + "/loans/" + loan["id"] + "/return", 200)["status"] == "RETURNED"
call("POST", L + "/loans/" + loan["id"] + "/return", 200)
assert call("GET", E + "/equipment/" + item["id"], 200)["available_quantity"] == 1
call(
    "POST",
    E + "/equipment",
    422,
    json={"name": "Invalid", "category": "Test", "total_quantity": 0},
)
call("GET", L + "/loans/" + str(uuid4()), 404)
call(
    "POST",
    L + "/loans",
    404,
    json={**request, "loan_id": str(uuid4()), "equipment_id": str(uuid4())},
)
# Real parallel requests compete for one inventory unit.
item2 = call(
    "POST",
    E + "/equipment",
    201,
    json={"name": "Concurrent Projector", "category": "AV", "total_quantity": 1},
)


def compete(_):
    body = {
        "loan_id": str(uuid4()),
        "equipment_id": item2["id"],
        "borrower_id": "concurrency-test",
    }
    response = httpx.post(L + "/loans", json=body, timeout=30)
    return response.status_code, response.json()


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    results = list(pool.map(compete, range(8)))
assert sorted(status for status, _ in results) == [201] + [409] * 7, results
assert call("GET", E + "/equipment/" + item2["id"], 200)["available_quantity"] == 0
records.append(
    {
        "check": "8 simultaneous borrowers for 1 unit",
        "statuses": [s for s, _ in results],
        "result": "PASS: exactly one ACTIVE loan",
    }
)
# Replay exactly the same request concurrently: all must resolve to one allocation.
item3 = call(
    "POST",
    E + "/equipment",
    201,
    json={"name": "Idempotency Laptop", "category": "Computing", "total_quantity": 2},
)
same_request = {
    "loan_id": str(uuid4()),
    "equipment_id": item3["id"],
    "borrower_id": "retry-test",
}


def replay(_):
    return httpx.post(L + "/loans", json=same_request, timeout=30)


with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    replies = list(pool.map(replay, range(6)))
assert all(r.status_code == 201 and r.json()["status"] == "ACTIVE" for r in replies), [
    r.text for r in replies
]
assert call("GET", E + "/equipment/" + item3["id"], 200)["available_quantity"] == 1
records.append(
    {
        "check": "6 simultaneous retries of same loan ID",
        "result": "PASS: one allocation",
    }
)
output = Path(os.getenv("EVIDENCE_FILE", "integration-results.json"))
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(
    json.dumps(
        {
            "run_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "checks": records,
            "result": "PASS",
        },
        indent=2,
    )
)
print(
    f"PASS: {len(records)} checks including concurrency and idempotency. Evidence: {output}"
)
