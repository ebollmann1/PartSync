# -*- coding: utf-8 -*-
"""Turn 14 API Client.

Handles authentication, pagination, bounded retries, and multi-environment
isolation (testing vs. production). Never logs credentials or bearer tokens.
"""
import logging
import time
from urllib.parse import parse_qs, urlparse

import requests

_logger = logging.getLogger(__name__)


class Turn14Error(Exception):
    """Base exception for Turn 14 API errors."""

    def __init__(self, message, retryable=False, retry_after=None, status_code=None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after
        self.status_code = status_code


class Turn14Client:
    """Client for Turn 14 API endpoints."""

    TEST_BASE_URL = "https://apitest.turn14.com/v1"
    PROD_BASE_URL = "https://api.turn14.com/v1"

    def __init__(self, environment="testing", client_id=None, client_secret=None, session=None):
        self.environment = environment or "testing"
        if self.environment not in ("testing", "production"):
            raise Turn14Error("Unknown Turn 14 environment.")
        self.base_url = self.PROD_BASE_URL if self.environment == "production" else self.TEST_BASE_URL
        self.client_id = (client_id or "").strip()
        self.client_secret = (client_secret or "").strip()
        self.session = session or requests.Session()
        self.token = None
        self.token_expiry = 0

    def close(self):
        _logger.debug("[Turn14Client] Closing HTTP session")
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _request(self, method, path, headers=None, **kwargs):
        url = self.base_url + path
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)

        params = kwargs.get("params")
        _logger.info("[Turn14Client] -> %s %s (params=%s)", method, url, params)

        try:
            response = self.session.request(
                method,
                url,
                headers=req_headers,
                timeout=(10, 60),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException as exc:
            _logger.error("[Turn14Client] Network error on %s %s: %s", method, url, exc)
            raise Turn14Error("Turn 14 request timed out or network error occurred.", retryable=True) from None

        _logger.info("[Turn14Client] <- HTTP %s from %s", response.status_code, url)

        if response.status_code == 429 or response.status_code >= 500:
            delay = response.headers.get("Retry-After", "")
            delay_sec = min(max(int(delay), 1), 86400) if delay.isdigit() else 5
            _logger.warning(
                "[Turn14Client] Service throttled or error HTTP %s. Retry-After: %s s",
                response.status_code,
                delay_sec,
            )
            raise Turn14Error(
                f"Turn 14 API service temporarily unavailable (HTTP {response.status_code}).",
                retryable=True,
                retry_after=delay_sec,
                status_code=response.status_code,
            )

        return response

    def _json(self, response):
        if not (200 <= response.status_code < 300):
            _logger.error(
                "[Turn14Client] API rejected request HTTP %s", response.status_code,
            )
            raise Turn14Error(
                f"Turn 14 API rejected request (HTTP {response.status_code}).",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError:
            _logger.error("[Turn14Client] Invalid JSON response")
            raise Turn14Error("Turn 14 API returned an invalid JSON response.") from None
        if not isinstance(body, dict):
            _logger.error("[Turn14Client] Unexpected response type: %s", type(body))
            raise Turn14Error("Turn 14 API returned an unexpected response structure.")
        return body

    def authenticate(self, force=False):
        """Authenticate via OAuth2 client_credentials grant."""
        if not force and self.token and time.time() < (self.token_expiry - 60):
            _logger.debug(
                "[Turn14Client] Reusing cached OAuth2 token (expires in %d s)",
                int(self.token_expiry - time.time()),
            )
            return self.token

        if not self.client_id or not self.client_secret:
            _logger.error("[Turn14Client] Client credentials missing for environment '%s'", self.environment)
            raise Turn14Error(f"Turn 14 {self.environment} client ID and secret must be configured.")

        response = self._request(
            "POST",
            "/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        body = self._json(response)
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            _logger.error("[Turn14Client] OAuth2 response missing access_token")
            raise Turn14Error("Turn 14 did not return a valid access token.")

        expires_in = body.get("expires_in")
        try:
            expires_sec = int(expires_in) if expires_in is not None else 3600
        except (ValueError, TypeError):
            expires_sec = 3600

        self.token = token
        self.token_expiry = time.time() + expires_sec
        _logger.info(
            "[Turn14Client] Successfully authenticated! Token expires in %d seconds",
            expires_sec,
        )
        return self.token

    def _auth_headers(self):
        token = self.authenticate()
        return {"Authorization": f"Bearer {token}"}

    def _get_resource(self, path, params=None):
        """Authenticated GET request with automatic single 401 retry."""
        headers = self._auth_headers()
        response = self._request("GET", path, headers=headers, params=params)
        if response.status_code == 401:
            _logger.warning("[Turn14Client] Received 401 Unauthorized; refreshing token and retrying...")
            self.authenticate(force=True)
            headers = self._auth_headers()
            response = self._request("GET", path, headers=headers, params=params)

        body = self._json(response)
        return body

    def test_connection(self):
        """Verify connectivity and credentials with a fresh token request only."""
        _logger.info("[Turn14Client] Executing test_connection for environment '%s'", self.environment)
        self.authenticate(force=True)
        _logger.info("[Turn14Client] Connection test successful")
        return {
            "success": True,
            "environment": self.environment,
        }

    def _collection(self, path, page=None, **params):
        if page is not None:
            params["page"] = page
        body = self._get_resource(path, params=params or None)
        data = body.get("data")
        if not isinstance(data, list):
            raise Turn14Error(f"Turn 14 {path} response must contain a data array.")
        return data, next_page(body, page or 1)

    def get_brands(self, page=None):
        """Return one page of all brands for manual reference synchronization."""
        return self._collection("/brands", page)

    def get_brand(self, brand_id):
        """Return a single brand record identified by its Turn 14 brand ID."""
        body = self._get_resource(f"/brands/{brand_id}")
        data = body.get("data")
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            raise Turn14Error("Turn 14 brand response must contain a brand object.")
        return data

    def get_locations(self):
        data, following = self._collection("/locations")
        while following:
            more, following = self._collection("/locations", page=following)
            data.extend(more)
        return data

    def get_items_by_brand(self, brand_id, page=1):
        """Return one product page belonging to the requested Turn 14 brand."""
        return self._collection(f"/items/brand/{brand_id}", page)

    def get_items_updates(self, page=1, days=1):
        return self._collection("/items/updates", page, days=min(max(int(days), 1), 15))

    def get_items_data(self, page=1):
        return self._collection("/items/data", page)

    def get_pricing(self, page=1):
        return self._collection("/pricing", page)

    def get_inventory(self, page=1):
        return self._collection("/inventory", page)

    def get_inventory_updates(self, page=1, minutes=15):
        minutes = minutes if minutes in {15, 30, 60, 240, 480, 1440} else 15
        return self._collection("/inventory/updates", page, minutes=minutes)

    def get_items_fitment(self, page=1):
        return self._collection("/items/fitment", page)


def next_page(body, current):
    """Determine the next page index from Turn 14 pagination metadata."""
    meta = body.get("meta") or {}
    total = meta.get("total_pages") if isinstance(meta, dict) else None
    if total is not None:
        if isinstance(total, bool) or not str(total).isdigit() or int(total) < 0:
            raise Turn14Error("Invalid total_pages in Turn 14 response.")
        if int(total) < current and not (int(total) == 0 and current == 1 and not body.get("data")):
            raise Turn14Error("Turn 14 returned an inconsistent page count.")
        return current + 1 if current < int(total) else None

    links = body.get("links")
    if isinstance(links, dict) and "next" in links:
        link = links["next"]
        if link is None or link == "":
            return None
        if isinstance(link, dict):
            link = link.get("href")
        if isinstance(link, str):
            pages = parse_qs(urlparse(link).query).get("page", [])
            if len(pages) == 1 and pages[0].isdigit() and int(pages[0]) == current + 1:
                return int(pages[0])
        raise Turn14Error("Invalid next-page link in Turn 14 response.")

    return None
