import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function LoadingMessage({
  label = "Loading your account…",
}: {
  label?: string;
}) {
  return (
    <main className="centered-page">
      <p role="status">{label}</p>
    </main>
  );
}

export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="auth-page">
      <section className="auth-card" aria-label="TeamFlow account">
        <Link className="brand" to="/login" aria-label="TeamFlow home">
          <span className="brand-mark" aria-hidden="true">
            T
          </span>
          TeamFlow
        </Link>
        {children}
      </section>
      <p className="auth-footer">A calmer way to move work forward.</p>
    </main>
  );
}

export function FieldError({
  id,
  children,
}: {
  id: string;
  children?: string;
}) {
  if (!children) return null;
  return (
    <span className="field-error" id={id}>
      {children}
    </span>
  );
}

export function RequestError({ children }: { children: string | null }) {
  if (!children) return null;
  return (
    <div className="error-banner" role="alert">
      {children}
    </div>
  );
}
