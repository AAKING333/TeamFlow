import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { RequestError } from "../components/AuthUi";
import { NotificationCenter } from "../components/NotificationCenter";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import type { Notification } from "../api/notifications";

export function AppShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [requestError, setRequestError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function openNotification(notification: Notification) {
    const query = new URLSearchParams({ workspace: String(notification.workspace_id) });
    if (notification.project_id !== null) {
      query.set("project", String(notification.project_id));
    }
    if (notification.task_id !== null) {
      query.set("task", String(notification.task_id));
    }
    navigate(`/app?${query.toString()}`);
  }

  async function handleLogout() {
    setSubmitting(true);
    setRequestError(null);
    try {
      await logout();
      navigate("/login", { replace: true });
    } catch (error) {
      setRequestError(
        error instanceof Error ? error.message : "Unable to sign out. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="brand" to="/app">
          <span className="brand-mark" aria-hidden="true">
            T
          </span>
          TeamFlow
        </Link>
        <nav aria-label="Account navigation">
          <Link to="/app">Account</Link>
          <NotificationCenter onNavigate={openNotification} />
          <span className="account-name">{user?.name}</span>
          <button
            className="quiet-button"
            disabled={submitting}
            onClick={handleLogout}
            type="button"
          >
            {submitting ? "Signing out…" : "Sign out"}
          </button>
        </nav>
      </header>
      <main className="dashboard">
        <p className="eyebrow">YOUR ACCOUNT</p>
        <h1>Welcome, {user?.name.split(" ")[0]}.</h1>
        <p className="dashboard-intro">
          Your TeamFlow account is set up and ready.
        </p>
        <WorkspaceSwitcher />
        <section className="account-card" aria-labelledby="account-heading">
          <div>
            <p className="eyebrow">PROFILE</p>
            <h2 id="account-heading">Account information</h2>
          </div>
          <dl>
            <div>
              <dt>Name</dt>
              <dd>{user?.name}</dd>
            </div>
            <div>
              <dt>Email</dt>
              <dd>{user?.email}</dd>
            </div>
          </dl>
          <RequestError>{requestError}</RequestError>
        </section>
      </main>
    </div>
  );
}
