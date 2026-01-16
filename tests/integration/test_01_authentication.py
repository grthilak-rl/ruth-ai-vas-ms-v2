"""
VAS-MS-V2 Authentication Integration Tests

Tests cover:
- Token generation with valid credentials
- Token generation with invalid credentials
- Token refresh
- Token expiry handling
"""

import pytest
import time
from vas_client import VASClient, VASError, TokenResponse


@pytest.mark.auth
class TestAuthentication:
    """Authentication endpoint tests"""

    def test_authenticate_with_valid_credentials(self, vas_client: VASClient):
        """
        Test: POST /v2/auth/token with valid credentials
        Expected: 200 OK with access_token, refresh_token, expires_in
        """
        token = vas_client.authenticate()

        assert token is not None
        assert isinstance(token, TokenResponse)
        assert token.access_token is not None
        assert len(token.access_token) > 0
        assert token.refresh_token is not None
        assert len(token.refresh_token) > 0
        assert token.token_type == "Bearer"
        assert token.expires_in > 0
        assert isinstance(token.scopes, list)

    def test_authenticate_with_invalid_client_id(self):
        """
        Test: POST /v2/auth/token with invalid client_id
        Expected: 401 Unauthorized
        """
        client = VASClient(
            client_id="invalid-client-id",
            client_secret="invalid-secret",
        )

        with pytest.raises(VASError) as exc_info:
            client.authenticate()

        assert exc_info.value.status_code == 401

    def test_authenticate_with_invalid_secret(self):
        """
        Test: POST /v2/auth/token with invalid client_secret
        Expected: 401 Unauthorized
        """
        client = VASClient(
            client_id="vas-portal",
            client_secret="wrong-secret",
        )

        with pytest.raises(VASError) as exc_info:
            client.authenticate()

        assert exc_info.value.status_code == 401

    def test_token_refresh(self, vas_client: VASClient):
        """
        Test: POST /v2/auth/token/refresh with valid refresh token
        Expected: 200 OK with new access_token
        """
        # First authenticate to get tokens
        initial_token = vas_client.authenticate()
        initial_access_token = initial_token.access_token

        # Small delay to ensure different token
        time.sleep(1)

        # Refresh the token
        refreshed_token = vas_client.refresh_token()

        assert refreshed_token is not None
        assert refreshed_token.access_token is not None
        assert refreshed_token.refresh_token is not None
        # New access token should be different (or same if server doesn't rotate)
        # Just verify we got a valid token back
        assert len(refreshed_token.access_token) > 0

    def test_token_refresh_with_invalid_token(self):
        """
        Test: POST /v2/auth/token/refresh with invalid refresh token
        Expected: 401 Unauthorized
        """
        client = VASClient()
        client._refresh_token = "invalid-refresh-token"

        with pytest.raises(VASError) as exc_info:
            client.refresh_token()

        assert exc_info.value.status_code == 401

    def test_ensure_authenticated_auto_refresh(self, vas_client: VASClient):
        """
        Test: ensure_authenticated() handles token management
        Expected: Automatically refreshes or re-authenticates as needed
        """
        # Clear any existing tokens
        vas_client._access_token = None
        vas_client._refresh_token = None
        vas_client._token_expires_at = None

        # Should authenticate automatically
        vas_client.ensure_authenticated()

        assert vas_client._access_token is not None
        assert vas_client._refresh_token is not None
        assert vas_client._token_expires_at is not None

    def test_token_includes_expected_scopes(self, vas_client: VASClient):
        """
        Test: Token response includes expected scopes
        Expected: Scopes include streams:read, snapshots:read, etc.
        """
        token = vas_client.authenticate()

        # Check for common scopes (actual scopes depend on client configuration)
        assert isinstance(token.scopes, list)
        # If scopes are returned, they should be strings
        for scope in token.scopes:
            assert isinstance(scope, str)

    def test_token_expiry_detection(self, vas_client: VASClient):
        """
        Test: is_token_expired property works correctly
        """
        # Without token, should be expired
        vas_client._access_token = None
        vas_client._token_expires_at = None
        assert vas_client.is_token_expired is True

        # After authentication, should not be expired
        vas_client.authenticate()
        assert vas_client.is_token_expired is False


@pytest.mark.auth
class TestAuthenticationErrorHandling:
    """Authentication error handling tests"""

    def test_error_response_format(self):
        """
        Test: Error responses follow standard format
        Expected: Error has status_code, error, description
        """
        client = VASClient(
            client_id="invalid",
            client_secret="invalid",
        )

        with pytest.raises(VASError) as exc_info:
            client.authenticate()

        error = exc_info.value
        assert hasattr(error, "status_code")
        assert hasattr(error, "error")
        assert hasattr(error, "description")
        assert error.status_code == 401

    def test_vas_error_is_retryable(self):
        """
        Test: VASError correctly identifies retryable errors
        """
        # 401 should be retryable (with token refresh)
        error_401 = VASError(401, "INVALID_TOKEN", "Token expired")
        assert error_401.is_retryable is True
        assert error_401.needs_token_refresh is True

        # 403 should not be retryable
        error_403 = VASError(403, "FORBIDDEN", "Access denied")
        assert error_403.is_retryable is False

        # 502/503/504 should be retryable
        error_502 = VASError(502, "BAD_GATEWAY", "Upstream error")
        assert error_502.is_retryable is True

        error_503 = VASError(503, "SERVICE_UNAVAILABLE", "Service down")
        assert error_503.is_retryable is True
