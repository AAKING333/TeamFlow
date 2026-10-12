# TeamFlow Frontend

The TeamFlow frontend is a React and TypeScript single-page application built
with Vite. It provides account registration, sign-in, and an authenticated
account shell. It does not store passwords, session cookies, or CSRF tokens in
local storage; the browser manages the HttpOnly session cookie.

## Prerequisites and setup

Install a supported Node.js release and npm, then run:

```powershell
cd D:\TeamFlow\frontend
npm install
Copy-Item .env.example .env.local
```

`VITE_API_BASE_URL` defaults to `http://localhost:5000/api/v1`. Set it in
`.env.local` only when the backend is running at another address. Vite exposes
`VITE_` variables to browser code, so never put secrets in this file.

Start the backend in a separate terminal. From the repository root, activate
the repository virtual environment before changing to `backend`:

```powershell
cd D:\TeamFlow
.\.venv\Scripts\Activate.ps1
cd backend
$env:APP_CONFIG = "development"
python run.py
```

Then start the frontend:

```powershell
cd D:\TeamFlow\frontend
npm run dev
```

Open the local Vite URL, normally `http://localhost:5173`. The backend's
`FRONTEND_ORIGIN` must exactly match that origin. The default is already
`http://localhost:5173`.

## Authentication flow

- Registration and login first request `GET /auth/csrf`, then include the
  session-bound token in `X-CSRF-Token` for their POST request.
- Each request includes `credentials: "include"` so the browser sends and
  receives the HttpOnly signed session cookie.
- After login, the frontend loads `GET /auth/me`; the backend remains the
  authority for every protected request.
- Logout fetches a fresh CSRF token and calls `POST /auth/logout`. The backend
  revokes all active sessions for the user.
- CSRF tokens and session values are never persisted in browser storage.

Routes are `/login`, `/register`, and protected `/app`. Client route guards
improve navigation only; they are not a security boundary.

## Checks

```powershell
npm test
npm run build
```

Tests use Vitest, jsdom, and Testing Library. `npm run build` runs the strict
TypeScript check before producing the Vite bundle.
