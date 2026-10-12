import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError, authApi } from "../api/auth";
import { AuthLayout, FieldError, RequestError } from "../components/AuthUi";

export function RegisterPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: Record<string, string> = {};
    if (!name.trim()) nextErrors.name = "Enter your name.";
    if (!email.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      nextErrors.email = "Enter a valid email address.";
    }
    if (password.length < 8 || password.length > 1024) {
      nextErrors.password = "Use a password between 8 and 1024 characters.";
    }
    if (password !== confirmation) {
      nextErrors.confirmation = "Passwords do not match.";
    }
    setErrors(nextErrors);
    setRequestError(null);
    if (Object.keys(nextErrors).length > 0) return;

    setSubmitting(true);
    try {
      await authApi.register({ name: name.trim(), email: email.trim(), password });
      navigate("/login", {
        replace: true,
        state: {
          notice: "Your account is ready. Sign in to continue.",
          from: (location.state as { from?: unknown } | null)?.from,
        },
      });
    } catch (error) {
      if (error instanceof ApiError && error.fields) {
        setErrors(error.fields);
      } else {
        setRequestError(
          error instanceof Error
            ? error.message
            : "Unable to create your account. Please try again.",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout>
      <div className="form-heading">
        <p className="eyebrow">GET STARTED</p>
        <h1>Create your account</h1>
        <p>Set up your TeamFlow account in a few steps.</p>
      </div>
      <RequestError>{requestError}</RequestError>
      <form onSubmit={handleSubmit} noValidate>
        <label htmlFor="register-name">Name</label>
        <input
          aria-describedby={errors.name ? "register-name-error" : undefined}
          aria-invalid={Boolean(errors.name)}
          autoComplete="name"
          id="register-name"
          maxLength={120}
          name="name"
          onChange={(event) => setName(event.target.value)}
          required
          value={name}
        />
        <FieldError id="register-name-error">{errors.name}</FieldError>

        <label htmlFor="register-email">Email address</label>
        <input
          aria-describedby={errors.email ? "register-email-error" : undefined}
          aria-invalid={Boolean(errors.email)}
          autoComplete="email"
          id="register-email"
          name="email"
          onChange={(event) => setEmail(event.target.value)}
          required
          type="email"
          value={email}
        />
        <FieldError id="register-email-error">{errors.email}</FieldError>

        <label htmlFor="register-password">Password</label>
        <input
          aria-describedby={errors.password ? "register-password-error" : undefined}
          aria-invalid={Boolean(errors.password)}
          autoComplete="new-password"
          id="register-password"
          maxLength={1024}
          minLength={8}
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
        <FieldError id="register-password-error">{errors.password}</FieldError>

        <label htmlFor="register-confirmation">Confirm password</label>
        <input
          aria-describedby={
            errors.confirmation ? "register-confirmation-error" : undefined
          }
          aria-invalid={Boolean(errors.confirmation)}
          autoComplete="new-password"
          id="register-confirmation"
          name="confirmation"
          onChange={(event) => setConfirmation(event.target.value)}
          required
          type="password"
          value={confirmation}
        />
        <FieldError id="register-confirmation-error">
          {errors.confirmation}
        </FieldError>

        <button className="primary-button" disabled={submitting} type="submit">
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="form-switch">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
