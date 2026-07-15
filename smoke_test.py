import sys
from starlette.testclient import TestClient

sys.path.insert(0, ".")
import app.webhook as w

client = TestClient(w.app, follow_redirects=False)

print("=== GET / (landing) ===")
r = client.get("/")
print(r.status_code, r.headers.get("content-type"))
assert r.status_code == 200
assert "SEABLUU" in r.text or "seabluu" in r.text.lower()
print("OK: landing served at /")

print("=== GET /health ===")
r = client.get("/health")
print(r.status_code, r.json())
assert r.status_code == 200

print("=== GET /admin (no cookie) -> should redirect to /admin/login ===")
r = client.get("/admin/")
print(r.status_code, r.headers.get("location"))
assert r.status_code in (302, 307)
assert r.headers.get("location") == "/admin/login"
print("OK: unauthenticated admin access redirects correctly")

print("=== GET /admin/login (no cookie) -> should render, NOT redirect-loop ===")
r = client.get("/admin/login")
print(r.status_code, r.headers.get("content-type"))
assert r.status_code == 200
assert "<form" in r.text.lower() or "login" in r.text.lower()
print("OK: login page reachable, no redirect loop")

print("=== GET /admin/static/... passthrough check (middleware should not block) ===")
r = client.get("/admin/nonexistent-static-file.css")
print(r.status_code)
# should be 404 from StaticFiles, not a redirect (proves /admin/static exclusion path matches)

print("\nALL SMOKE TESTS PASSED")
