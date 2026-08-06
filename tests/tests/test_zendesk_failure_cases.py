import os
import requests

BASE_URL = "http://localhost:8080"
API_KEY = "Jdkwpeirutje8264jdjwt2ufoc93jsg"
AUTH_HEADERS = {"X-API-Key": API_KEY}


def test_certificate_for_nonexistent_ticket_returns_404():
    response = requests.get(
        f"{BASE_URL}/api/v1/financial-certificate/DOES-NOT-EXIST",
        params={"tenant_id": "test_tenant"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"


def test_cfo_dashboard_missing_tenant_id_returns_422():
    response = requests.get(
        f"{BASE_URL}/api/v1/cfo/financial-leakage",
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422, f"Expected 422 (missing required param), got {response.status_code}"


def test_cfo_dashboard_unknown_tenant_returns_empty_not_error():
    response = requests.get(
        f"{BASE_URL}/api/v1/cfo/financial-leakage",
        params={"tenant_id": "tenant_that_has_never_existed"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_active_breaches"] == 0
    assert data["total_financial_exposure_usd"] == "0"


def test_coo_dashboard_unknown_tenant_returns_empty_not_error():
    response = requests.get(
        f"{BASE_URL}/api/v1/coo/root-cause-attribution",
        params={"tenant_id": "tenant_that_has_never_existed"},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tickets_analyzed"] == 0


def test_missing_api_key_returns_401():
    response = requests.get(
        f"{BASE_URL}/api/v1/cfo/financial-leakage",
        params={"tenant_id": "test_tenant"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing X-API-Key header"


def test_wrong_api_key_returns_401():
    response = requests.get(
        f"{BASE_URL}/api/v1/cfo/financial-leakage",
        params={"tenant_id": "test_tenant"},
        headers={"X-API-Key": "not-the-real-key"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"
