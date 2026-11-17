"""Fake Supabase signing keys and tokens: real ES256 signatures, no Supabase involved."""

import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from backend.api.auth import TokenVerifier

ISSUER = "https://fake-project.supabase.co/auth/v1"

PROJECT_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())  # some other project's key


def mint(
    user_id: uuid.UUID | str,
    *,
    key: Any = PROJECT_KEY,
    algorithm: str = "ES256",
    **overrides: Any,
) -> str:
    """A token shaped like a Supabase access token for a signed-in user."""
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "aud": "authenticated",
        "iss": ISSUER,
        "role": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": "fake-kid"})


def fake_verifier() -> TokenVerifier:
    """Verifies against the fake project's public key, like the JWKS lookup would."""
    public_key = PROJECT_KEY.public_key()
    return TokenVerifier(lambda token: public_key, ISSUER)
