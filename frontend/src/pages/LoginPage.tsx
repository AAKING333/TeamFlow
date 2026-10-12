import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError, authApi } from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { AuthLayout, FieldError, RequestError } from "../components/AuthUi";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { refreshUser } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const notice = (location.state as { notice?: string } | null)?.notice;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      nextErrors.email = "Enter a valid email address.";
    }
    if (password.length < 8 || password.length > 1024) {
      nextErrors.password = "Use a password between 8 and 1024 characters.";
    }
    setErrors(nextErrors);
    setRequestError(null);
    if (Object.keys(nextErrors).length > 0) return;
    setSubmitting(true);
    try {
      await authApi.login({ email: email.trim(), password });
      await refreshUser();
      const destination =
        (location.state as { from?: { pathname?: string } } | null)?.from
          ?.pathname ?? "/app";
      const search =
        (location.state as { from?: { search?: string } } | null)?.from?.search ?? "";
      navigate(`${destination}${search}`, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.fields) {
        setErrors(error.fields);
      } else {
        setRequestError(
          error instanceof Error
            ? error.message
            : "Unable to sign in. Please try again.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      <div className="form-heading">
        <p className="eyebrow">WELCOME BACK</p>
        <h1>Sign in to TeamFlow</h1>
        <p>Pick up where your team left off.</p>
      </div>
      {notice && (
        <p className="success-banner" role="status">
          {notice}
        </p>
      )}
      <RequestError>{requestError}</RequestError>
      <form onSubmit={handleSubmit} noValidate>
        <label htmlFor="login-email">Email address</label>
        <input
          aria-describedby={errors.email ? "login-email-error" : undefined}
          aria-invalid={Boolean(errors.email)}
          autoComplete="email"
          id="login-email"
          name="email"
          onChange={(event) => setEmail(event.target.value)}
          required
          type="email"
          value={email}
        />
        <FieldError id="login-email-error">{errors.email}</FieldError>

        <label htmlFor="login-password">Password</label>
        <input
          aria-describedby={errors.password ? "login-password-error" : undefined}
          aria-invalid={Boolean(errors.password)}
          autoComplete="current-password"
          id="login-password"
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
        <FieldError id="login-password-error">{errors.password}</FieldError>

        <button className="primary-button" disabled={submitting} type="submit">
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="form-switch">
        New to TeamFlow? <Link to="/register">Create an account</Link>
      </p>
    </AuthLayout>
  );
}
