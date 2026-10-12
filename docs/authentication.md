# Authentication Design

## Chosen approach

TeamFlow uses Flask's built-in signed-cookie session. The browser stores an
HttpOnly cookie containing a signed session payload; it does not store a
password, bearer token, or application secret. A signed cookie is tamper
resistant, but its contents are not encrypted, so only a user ID, a session
version, an issue time, and a CSRF token are stored in it.

The `users.session_version` value enables server-side revocation without adding
a session-storage service. Protected requests compare the version in the signed
cookie with the current database value. Logout increments the database value
before clearing the browser cookie, invalidating any copied older cookie.
This deliberately revokes every active browser session for that user; the
milestone prioritizes reliable revocation without a session table over
per-device logout.

## Session lifecycle

1. The browser requests `GET /api/v1/auth/csrf` and receives a CSRF token.
2. It sends that token in `X-CSRF-Token` when registering, logging in, or
   logging out.
3. Successful login clears the pre-authentication cookie state, then creates a
   new signed session with the user ID, session version, issue time, and a
   rotated CSRF token.
4. The signed cookie is HttpOnly, uses `SameSite=Lax`, and is marked Secure in
   production. Authenticated sessions expire after 30 minutes of inactivity
   and have a 12-hour absolute lifetime.
5. `GET /api/v1/auth/me` verifies the signed session, age, user record, and
   session version. Missing, invalid, expired, or revoked sessions receive the
   same generic HTTP 401 response.
6. Logout increments the user session version, commits that change, then clears
   the client session. A replay of the previous signed cookie is rejected, and
   other active sessions for that user are rejected as well.

Flask's cookie session has no server-side session identifier to regenerate.
Clearing pre-authentication state before setting authenticated values prevents
pre-login session data from being carried into the authenticated state. The
rotated CSRF token and server-checked session version further separate the
authenticated session from an older cookie.

## CSRF and CORS

All state-changing requests on the auth blueprint require a session-bound
`X-CSRF-Token`. Fetch a token from `/api/v1/auth/csrf`; after login, fetch it
again because login rotates the token. The browser must not place the token or
session cookie in local storage.

Credentialed CORS is restricted to the single configured `FRONTEND_ORIGIN`.
Local development defaults to `http://localhost:5173`; use `http://localhost`
for the backend host as well so both origins are same-site despite their
different ports. Browser requests must use `credentials: "include"`.
Production must configure the exact trusted frontend origin and serve over
HTTPS; wildcard CORS is not supported.

## Rate limiting

The application does not keep process-local counters because they reset on
restart and are inconsistent across workers. Before public deployment, enforce
rate limits at the trusted edge (CDN, WAF, or reverse proxy), at minimum on
`POST /api/v1/auth/login` and `POST /api/v1/auth/register`. Use the connection
source address seen by the trusted proxy; only honor forwarded client IP
headers when the deployment's proxy chain is explicitly configured and
validated. A starting Nginx policy is:

```nginx
http {
    limit_req_zone $binary_remote_addr zone=teamflow_auth:10m rate=10r/m;

    server {
        location = /api/v1/auth/login {
            limit_req zone=teamflow_auth burst=5 nodelay;
            proxy_pass http://127.0.0.1:5000;
        }

        location = /api/v1/auth/register {
            limit_req zone=teamflow_auth burst=3 nodelay;
            proxy_pass http://127.0.0.1:5000;
        }
    }
}
```

Configure this at the actual public edge and add an account/email dimension
where supported. Do not trust forwarded client IP headers unless the trusted
proxy chain is explicitly configured. Monitor false positives and never log
passwords or full request bodies.

## API contract

- `POST /api/v1/auth/login`: validates email and password, returns a generic
  HTTP 401 for either an unknown email or an incorrect password, and sets the
  signed session only after successful verification.
- `GET /api/v1/auth/me`: returns the authenticated user's safe profile or HTTP
  401.
- `POST /api/v1/auth/logout`: requires CSRF validation, revokes the old session,
  and returns an idempotent success response.
- `GET /api/v1/auth/csrf`: returns the CSRF token required by state-changing
  authentication requests.

Responses contain public profile fields only; password hashes and secrets are
never serialized.
