"""The API contract: the endpoints the web page depends on must exist, be documented, and stay protected.

If someone renames or removes an endpoint, this test fails before the web page breaks.
"""
from app.main import app

# (method, path) pairs that static/app.js calls. Changing one is a breaking change.
CONTRACT = {
    ("post", "/api/login"), ("post", "/api/logout"), ("get", "/api/health"),
    ("get", "/api/status"), ("get", "/api/settings"), ("put", "/api/settings/{name}"),
    ("get", "/api/roles"), ("put", "/api/roles"), ("post", "/api/roles/{role_id}/resume"),
    ("get", "/api/jobs"), ("post", "/api/jobs"), ("get", "/api/jobs/{job_id}"),
    ("post", "/api/jobs/skip"), ("post", "/api/jobs/tailor"),
    ("patch", "/api/jobs/{job_id}"), ("post", "/api/jobs/{job_id}/approve"), ("post", "/api/jobs/{job_id}/retry"),
    ("get", "/api/jobs/{job_id}/{kind}.docx"),
    ("post", "/api/search/run"), ("post", "/api/push/subscribe"),
}
PUBLIC = {("post", "/api/login"), ("post", "/api/logout"), ("get", "/api/health")}


def schema_ops():
    paths = app.openapi()["paths"]
    return {(m, p): op for p, ops in paths.items() for m, op in ops.items()}


def test_every_endpoint_in_contract_exists():
    missing = CONTRACT - set(schema_ops())
    assert not missing, f"Endpoints the web page needs are gone: {sorted(missing)}"


def test_every_endpoint_is_documented():
    for key, op in schema_ops().items():
        assert op.get("summary") and op.get("tags"), f"{key} has no summary or tag in /docs"


def test_background_work_returns_202(client):
    # 202 Accepted = "got it, working on it": the client should poll, not wait.
    ops = schema_ops()
    for key in [("post", "/api/jobs/tailor"), ("post", "/api/search/run"), ("post", "/api/jobs/{job_id}/approve")]:
        assert "202" in ops[key]["responses"], key


def test_private_endpoints_need_sign_in(client):
    client.cookies.clear()
    for method, path in CONTRACT - PUBLIC:
        url = path.replace("{name}", "profile").replace("{job_id}", "x").replace("{kind}", "resume").replace("{role_id}", "ba")
        r = client.request(method.upper(), url, json={})
        assert r.status_code == 401, f"{method.upper()} {url} answered {r.status_code} without sign-in"
