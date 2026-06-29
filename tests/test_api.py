from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # Allows core tests to run before optional web dependencies are installed.
    TestClient = None


@unittest.skipIf(TestClient is None, "FastAPI test dependency is not installed")
class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.main import app

        cls.client = TestClient(app)

    def test_health_and_security_headers(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_invalid_report_session_is_friendly(self):
        response = self.client.post(
            "/api/reports/single-token",
            json={
                "session_id": "x" * 32,
                "margin_currency": "INR",
                "from_ist": "21/06/26 09:15:00",
                "to_ist": "21/06/26 23:59:59",
                "token": "B-SOL_USDT",
                "initial_capital": 20000,
                "page_size": 100,
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["success"])
        self.assertNotIn("Traceback", response.text)

    def test_auth_secret_is_not_returned(self):
        with patch("backend.main.CoinDCXClient") as client_class:
            instance = client_class.return_value
            instance.get_transactions.return_value = []
            response = self.client.post(
                "/api/auth/test",
                json={"api_key": "key-value", "api_secret": "super-secret-value", "margin_currency": "INR"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertNotIn("super-secret-value", response.text)
        self.assertNotIn("key-value", response.text)

    def test_download_traversal_is_not_served(self):
        response = self.client.get("/api/download/not-valid/summary.json")
        self.assertIn(response.status_code, {400, 404, 422})


if __name__ == "__main__":
    unittest.main()

