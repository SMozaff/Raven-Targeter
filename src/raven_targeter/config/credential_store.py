"""Secure credential storage for Raven-Targeter.

Secrets are stored in the operating-system keychain through ``keyring``.
The GUI never writes API tokens into the repository, SQLite database, or
application settings. Environment variables remain supported as an explicit
advanced/CI override, but the desktop workflow prefers the OS keychain.
"""
from __future__ import annotations

from typing import Protocol

try:  # Keep the module testable in stripped development environments.
    import keyring as _system_keyring
    import keyring.errors as _keyring_errors
except ImportError:  # pragma: no cover - dependency is required by pyproject in real installs
    _system_keyring = None
    _keyring_errors = None

SERVICE_NAME = "Raven-Targeter"
GITHUB_TOKEN_ACCOUNT = "github-token"
SEARCH_API_KEY_ACCOUNT = "search-api-key"


class CredentialStoreError(RuntimeError):
    """Raised when the OS credential store cannot complete an operation."""


class KeyringLike(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...
    def set_password(self, service_name: str, username: str, password: str) -> None: ...
    def delete_password(self, service_name: str, username: str) -> None: ...


class SecureCredentialStore:
    """Small facade around the user's OS keychain.

    A backend can be injected by tests. Production code uses the system
    ``keyring`` backend and never silently falls back to an in-memory store.
    """

    def __init__(self, backend: KeyringLike | None = None) -> None:
        if backend is not None:
            self._backend = backend
        elif _system_keyring is not None:
            self._backend = _system_keyring
        else:
            self._backend = None

    def _require_backend(self) -> KeyringLike:
        if self._backend is None:
            raise CredentialStoreError(
                "OS keychain support is unavailable because the keyring package is not installed"
            )
        return self._backend

    @staticmethod
    def _is_delete_missing(exc: Exception) -> bool:
        return bool(
            _keyring_errors is not None
            and isinstance(exc, _keyring_errors.PasswordDeleteError)
        )

    def _get(self, account: str) -> str | None:
        try:
            value = self._require_backend().get_password(SERVICE_NAME, account)
        except Exception as exc:  # third-party keyring backends expose multiple exception types
            if isinstance(exc, CredentialStoreError):
                raise
            raise CredentialStoreError(str(exc)) from exc
        return value.strip() if value and value.strip() else None

    def _set(self, account: str, value: str) -> None:
        clean = value.strip()
        if not clean:
            raise ValueError("Credential cannot be empty")
        try:
            self._require_backend().set_password(SERVICE_NAME, account, clean)
        except Exception as exc:
            if isinstance(exc, CredentialStoreError):
                raise
            raise CredentialStoreError(str(exc)) from exc

    def _delete(self, account: str) -> None:
        try:
            self._require_backend().delete_password(SERVICE_NAME, account)
        except Exception as exc:
            if self._is_delete_missing(exc):
                return
            if isinstance(exc, CredentialStoreError):
                raise
            raise CredentialStoreError(str(exc)) from exc

    def get_github_token(self) -> str | None:
        return self._get(GITHUB_TOKEN_ACCOUNT)

    def set_github_token(self, token: str) -> None:
        self._set(GITHUB_TOKEN_ACCOUNT, token)

    def clear_github_token(self) -> None:
        self._delete(GITHUB_TOKEN_ACCOUNT)

    def get_search_api_key(self) -> str | None:
        return self._get(SEARCH_API_KEY_ACCOUNT)

    def set_search_api_key(self, api_key: str) -> None:
        self._set(SEARCH_API_KEY_ACCOUNT, api_key)

    def clear_search_api_key(self) -> None:
        self._delete(SEARCH_API_KEY_ACCOUNT)
