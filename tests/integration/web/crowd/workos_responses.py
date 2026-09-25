"""WorkOS AuthKit responses shaped like the API sends them, for login tests."""

import base64
import json

from workos.user_management.models import AuthenticateResponse

AUTHENTICATE = "workos.user_management._resource.UserManagement.authenticate_with_code"
SESSION_ID = "session_01TESTSESSION"


def _segment(claims):
    raw = json.dumps(claims).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def access_token(session_id=SESSION_ID):
    return f"{_segment({'alg': 'RS256'})}.{_segment({'sid': session_id})}.sig"


def authenticate_response(user_id, **user):
    return AuthenticateResponse.from_dict(
        {
            "user": (
                {
                    "object": "user",
                    "id": user_id,
                    "first_name": None,
                    "last_name": None,
                    "profile_picture_url": None,
                    "email": f"{user_id.lower()}@example.com",
                    "email_verified": True,
                    "external_id": None,
                    "last_sign_in_at": None,
                    "created_at": "2026-09-25T12:00:00.000Z",
                    "updated_at": "2026-09-25T12:00:00.000Z",
                }
                | user
            ),
            "access_token": access_token(),
            "refresh_token": "refresh",
        }
    )
