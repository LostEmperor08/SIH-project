"""
Security control regression tests — pytest tests/ -v

Covers the nine controls from the project report. Run these in CI; they are
the evidence that the controls described in the report are actually present
in the code, which is a different claim from "we wrote them down once".
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("ENVIRONMENT", "development")

from fastapi.testclient import TestClient            # noqa: E402

from app import security                             # noqa: E402
from app.config import Settings, get_settings        # noqa: E402
from app.security import Officer, RateLimiter        # noqa: E402
from main import app                                 # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    security.limiter.reset()
    security._token_cache.clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def as_officer(role: str = "analyst", oid: str = "officer-1"):
    """Bypass Supabase Auth for tests that are not testing auth itself."""
    async def _dep():
        return Officer(id=oid, email=f"{role}@lea.gov.in", role=role)
    return _dep


# =====================================================================
# Control 1 + 2: fail-closed authentication
# =====================================================================
class TestFailClosedAuth:
    def test_health_is_public(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_health_leaks_no_secrets(self, client):
        body = r"" + client.get("/health").text
        for secret in ("test-service-key", "test-anon-key", "supabase.co"):
            assert secret not in body, f"/health leaked {secret}"

    def test_trace_requires_auth(self, client):
        r = client.post("/trace", json={
            "targets": [{"chain": "btc",
                         "address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"}]})
        assert r.status_code == 401

    def test_no_mock_identity_fallback(self, client):
        """There must be no dev bypass that invents an officer."""
        r = client.post("/trace", headers={"Authorization": "Bearer totally-fake"},
                        json={"targets": [{"chain": "btc",
                              "address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"}]})
        # 401 (rejected) or 503 (auth unreachable) — never 200
        assert r.status_code in (401, 503)

    def test_threat_intel_requires_auth(self, client):
        assert client.post("/threat-intel/sync", json={"sources": ["ofac"]}).status_code == 401

    def test_dossier_requires_auth(self, client):
        r = client.post("/dossier/review",
                        json={"dossier_id": "DSR-1", "decision": "approved"})
        assert r.status_code == 401


# =====================================================================
# Control 3: constant-time service key comparison
# =====================================================================
class TestServiceKey:
    def test_short_key_is_refused_as_configuration(self):
        s = Settings(supabase_url="https://x.supabase.co", supabase_anon_key="k",
                     service_api_key="short")
        assert s.has_service_key is False, "a 5-char key must not count as configured"

    def test_long_key_is_accepted(self):
        s = Settings(supabase_url="https://x.supabase.co", supabase_anon_key="k",
                     service_api_key="z" * 40)
        assert s.has_service_key is True

    def test_uses_compare_digest(self):
        """
        Assert on the parsed AST, not on the source text — a docstring that
        mentions '==' is not a timing leak, and a test that can't tell the
        difference will eventually be silenced rather than fixed.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(security._verify_service_key)))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        names = {
            (n.func.attr if isinstance(n.func, ast.Attribute) else
             getattr(n.func, "id", None))
            for n in calls
        }
        assert "compare_digest" in names, "service key must use hmac.compare_digest"

        # no ==/!= comparison anywhere in the function body
        compares = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)]
        bad = [c for c in compares
               if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in c.ops)]
        assert not bad, f"found {len(bad)} equality comparison(s) in secret handling"

    def test_wrong_key_rejected(self, client):
        get_settings.cache_clear()
        os.environ["SERVICE_API_KEY"] = "s" * 40
        try:
            get_settings.cache_clear()
            r = client.post("/trace", headers={"x-api-key": "w" * 40},
                            json={"targets": [{"chain": "btc",
                                  "address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"}]})
            assert r.status_code == 401
        finally:
            os.environ.pop("SERVICE_API_KEY", None)
            get_settings.cache_clear()


# =====================================================================
# Control 4: per-identity rate limiting
# =====================================================================
class TestRateLimiting:
    def test_blocks_after_limit(self):
        rl = RateLimiter()
        for _ in range(5):
            assert rl.check("officer-A", 5, 60)[0] is True
        allowed, _, retry = rl.check("officer-A", 5, 60)
        assert allowed is False and retry > 0

    def test_is_per_identity(self):
        rl = RateLimiter()
        for _ in range(5):
            rl.check("officer-A", 5, 60)
        assert rl.check("officer-A", 5, 60)[0] is False
        # a different officer is unaffected
        assert rl.check("officer-B", 5, 60)[0] is True

    def test_buckets_are_independent(self):
        rl = RateLimiter()
        for _ in range(3):
            rl.check("trace:officer-A", 3, 60)
        assert rl.check("trace:officer-A", 3, 60)[0] is False
        assert rl.check("graph:officer-A", 3, 60)[0] is True

    def test_window_slides(self):
        rl = RateLimiter()
        for _ in range(2):
            rl.check("x", 2, 1)
        assert rl.check("x", 2, 1)[0] is False
        import time
        time.sleep(1.05)
        assert rl.check("x", 2, 1)[0] is True

    def test_429_returned_with_retry_after(self, client):
        from app.security import get_current_officer
        app.dependency_overrides[get_current_officer] = as_officer("investigator")
        codes = [client.post("/threat-intel/sync", json={"sources": []}).status_code
                 for _ in range(8)]
        assert 429 in codes, f"rate limit never fired: {codes}"


# =====================================================================
# Control 5: strict chain allowlist and address validation
# =====================================================================
class TestValidation:
    @pytest.fixture(autouse=True)
    def _auth(self):
        from app.security import get_current_officer
        app.dependency_overrides[get_current_officer] = as_officer("analyst")

    def test_unknown_chain_rejected(self, client):
        r = client.post("/trace", json={
            "targets": [{"chain": "dogecoin", "address": "D" * 34}]})
        assert r.status_code == 422

    def test_eth_address_on_btc_chain_rejected(self, client):
        r = client.post("/trace", json={"targets": [
            {"chain": "btc", "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"}]})
        assert r.status_code == 422

    def test_path_traversal_rejected(self, client):
        r = client.post("/trace", json={"targets": [
            {"chain": "eth", "address": "../../../../etc/passwd"}]})
        assert r.status_code == 422

    def test_sql_injection_string_rejected(self, client):
        r = client.post("/trace", json={"targets": [
            {"chain": "btc", "address": "'; DROP TABLE wallets; --"}]})
        assert r.status_code == 422

    def test_hops_capped(self, client):
        r = client.post("/trace", json={
            "targets": [{"chain": "btc",
                         "address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"}],
            "hops": 99})
        assert r.status_code == 422

    def test_too_many_targets_rejected(self, client):
        r = client.post("/trace", json={"targets": [
            {"chain": "eth", "address": f"0x{i:040x}"} for i in range(1, 15)]})
        assert r.status_code == 422

    def test_duplicate_targets_rejected(self, client):
        a = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
        r = client.post("/trace", json={"targets": [
            {"chain": "btc", "address": a}, {"chain": "btc", "address": a}]})
        assert r.status_code == 422

    def test_valid_addresses_accepted_by_validator(self):
        from app.schemas import is_valid_address
        assert is_valid_address("btc", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
        assert is_valid_address("btc", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        assert is_valid_address("btc", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
        assert is_valid_address("eth", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
        assert is_valid_address("tron", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")

    def test_evm_address_lowercased(self):
        from app.schemas import Target
        t = Target(chain="eth", address="0xD8DA6BF26964AF9D7EED9E03E53415D37AA96045")
        assert t.address == "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"

    def test_btc_address_case_preserved(self):
        from app.schemas import Target
        a = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert Target(chain="btc", address=a).address == a


# =====================================================================
# Control 6: restricted CORS
# =====================================================================
class TestCORS:
    def test_allowed_origin_echoed(self, client):
        r = client.options("/health", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_unknown_origin_not_echoed(self, client):
        r = client.options("/health", headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET"})
        assert r.headers.get("access-control-allow-origin") != "https://evil.example.com"

    def test_wildcard_refused_in_production(self):
        with pytest.raises(Exception):
            Settings(supabase_url="https://x.supabase.co", supabase_anon_key="k",
                     environment="production", cors_origins="*")


# =====================================================================
# Controls 7 + 8: role enforcement
# =====================================================================
class TestRoles:
    def test_viewer_cannot_trace(self, client):
        from app.security import get_current_officer
        app.dependency_overrides[get_current_officer] = as_officer("viewer")
        r = client.post("/trace", json={"targets": [
            {"chain": "btc", "address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"}]})
        assert r.status_code == 403

    def test_analyst_cannot_sync_threat_intel(self, client):
        from app.security import get_current_officer
        app.dependency_overrides[get_current_officer] = as_officer("analyst")
        assert client.post("/threat-intel/sync",
                           json={"sources": []}).status_code == 403

    def test_investigator_cannot_review_dossier(self, client):
        from app.security import get_current_officer
        app.dependency_overrides[get_current_officer] = as_officer("investigator")
        r = client.post("/dossier/review",
                        json={"dossier_id": "DSR-1", "decision": "approved"})
        assert r.status_code == 403

    def test_service_key_cannot_review_dossier(self, client):
        """A machine credential must not approve a dossier — that needs a person."""
        from app.security import get_current_officer

        async def _svc():
            return Officer(id="service", email=None, role="admin", is_service=True)
        app.dependency_overrides[get_current_officer] = _svc
        r = client.post("/dossier/review",
                        json={"dossier_id": "DSR-1", "decision": "approved"})
        assert r.status_code == 403

    def test_role_ranking(self):
        assert Officer("x", None, "viewer").rank < Officer("x", None, "analyst").rank
        assert Officer("x", None, "analyst").rank < Officer("x", None, "investigator").rank
        assert Officer("x", None, "investigator").rank < Officer("x", None, "admin").rank


# =====================================================================
# Response hygiene
# =====================================================================
class TestResponseHygiene:
    def test_security_headers_present(self, client):
        h = client.get("/health").headers
        assert h["X-Content-Type-Options"] == "nosniff"
        assert h["X-Frame-Options"] == "DENY"
        assert h["Referrer-Policy"] == "no-referrer"

    def test_request_id_returned(self, client):
        assert client.get("/health").headers.get("X-Request-ID")

    def test_request_id_echoed_when_supplied(self, client):
        r = client.get("/health", headers={"x-request-id": "abc123"})
        assert r.headers["X-Request-ID"] == "abc123"

    def test_validation_errors_are_readable(self, client):
        from app.security import get_current_officer
        app.dependency_overrides[get_current_officer] = as_officer("analyst")
        r = client.post("/trace", json={"targets": [
            {"chain": "btc", "address": "not-an-address"}]})
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "validation_failed"
        assert "requestId" in body
