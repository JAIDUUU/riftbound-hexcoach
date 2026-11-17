"""Verify the Supabase Auth JWT the frontend sends as a bearer token.

Supabase signs user access tokens with asymmetric keys published as a JWKS, so
verification needs only the project URL: no shared secret. The signing-key lookup is
injected, so tests verify real signatures against locally generated keys and never
call Supabase.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import jwt

SigningKeyFor = Callable[[str], Any]
"""Returns the public key that should have signed this token (selected by its `kid`)."""

# Asymmetric only: accepting HS256 next to a published public key invites key confusion.
ALGORITHMS = ("ES256", "RS256")
AUDIENCE = "authenticated"  # Supabase's audience for signed-in users; the anon key has none


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: uuid.UUID


class AuthError(Exception):
    """The token is missing, malformed, expired, or not signed by our Supabase project."""


class AuthUnavailableError(Exception):
    """The signing keys could not be fetched, so no token can be judged right now."""


@dataclass(frozen=True, slots=True)
class TokenVerifier:
    signing_key_for: SigningKeyFor
    issuer: str

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self.signing_key_for(token),
                algorithms=list(ALGORITHMS),
                audience=AUDIENCE,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWKClientConnectionError as error:
            raise AuthUnavailableError("Could not fetch the Supabase signing keys.") from error
        except jwt.PyJWTError as error:
            raise AuthError(f"Invalid token: {error}") from error
        # Anonymous sessions also carry aud=authenticated; Grill Decisions requires real
        # (OAuth) accounts, so they are refused even if the project ever enables them.
        if claims.get("is_anonymous") is True:
            raise AuthError("Anonymous sessions cannot use the API; sign in with OAuth.")
        try:
            return AuthenticatedUser(id=uuid.UUID(str(claims["sub"])))
        except ValueError:
            raise AuthError("Token subject is not a user id.") from None


def supabase_verifier(supabase_url: str) -> TokenVerifier:
    """A verifier for tokens issued by the Supabase project at `supabase_url`."""
    base = supabase_url.rstrip("/")
    keys = jwt.PyJWKClient(f"{base}/auth/v1/.well-known/jwks.json", cache_keys=True)
    return TokenVerifier(lambda token: keys.get_signing_key_from_jwt(token).key, f"{base}/auth/v1")
