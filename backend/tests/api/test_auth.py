import base64
import json
import time
import uuid
from collections.abc import Mapping

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from backend.api.auth import AuthError, AuthUnavailableError, TokenVerifier
from tests.api.tokens import ISSUER, OTHER_KEY, PROJECT_KEY, fake_verifier, mint

USER = uuid.UUID("7d1f2c3a-0000-4000-8000-000000000001")


def test_a_valid_token_yields_the_user_id_from_its_subject() -> None:
    assert fake_verifier().verify(mint(USER)).id == USER
    assert fake_verifier().verify(mint(USER, is_anonymous=False)).id == USER  # OAuth users


@pytest.mark.parametrize(
    ("token", "why"),
    [
        (mint(USER, exp=int(time.time()) - 10), "expired"),
        (mint(USER, aud=None), "no audience - e.g. the anon key itself"),
        (mint(USER, aud="anon"), "wrong audience"),
        (mint(USER, iss="https://other-project.supabase.co/auth/v1"), "another project"),
        (mint(USER, key=OTHER_KEY), "signed by a key that isn't ours"),
        (mint(USER, exp=None), "never expires"),
        (mint("service-role"), "subject is not a user id"),
        (mint(USER, is_anonymous=True), "anonymous session, not a real account"),
        ("not.a.jwt", "garbage"),
    ],
)
def test_bad_tokens_are_rejected(token: str, why: str) -> None:
    with pytest.raises(AuthError):
        fake_verifier().verify(token)


def test_hs256_tokens_are_rejected_whatever_secret_signed_them() -> None:
    # Key confusion: an attacker HMAC-signs with material from the published public key.
    public_pem = PROJECT_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    forged = jwt.encode(
        {"sub": str(USER), "aud": "authenticated", "iss": ISSUER, "exp": time.time() + 60},
        public_pem.hex(),
        algorithm="HS256",
    )

    with pytest.raises(AuthError):
        fake_verifier().verify(forged)


def test_an_unsigned_alg_none_token_is_rejected() -> None:
    def segment(part: Mapping[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()

    claims = {"sub": str(USER), "aud": "authenticated", "iss": ISSUER, "exp": time.time() + 60}
    unsigned = f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(claims)}."

    with pytest.raises(AuthError):
        fake_verifier().verify(unsigned)


def test_unreachable_signing_keys_are_an_outage_not_a_bad_token() -> None:
    def keys_down(token: str) -> object:
        raise jwt.PyJWKClientConnectionError("JWKS fetch timed out")

    with pytest.raises(AuthUnavailableError):
        TokenVerifier(keys_down, ISSUER).verify(mint(USER))
