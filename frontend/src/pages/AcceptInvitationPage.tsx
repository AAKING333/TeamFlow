import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { workspaceApi } from "../api/workspaces";
import { useAuth } from "../auth/AuthContext";
import { AuthLayout } from "../components/AuthUi";

function invitationError(error: unknown) {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : "The invitation could not be accepted.";
  }
  if (error.code === "invitation_email_mismatch") {
    return "This invitation belongs to a different account. Sign in with the invited email.";
  }
  if (error.code === "invitation_unavailable") {
    return "This invitation has expired, been revoked, or was already used.";
  }
  if (error.code === "invitation_not_found") {
    return "This invitation link is invalid.";
  }
  return error.message;
}

export function AcceptInvitationPage() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [token, setToken] = useState(() => new URLSearchParams(location.search).get("token"));
  const [requestError, setRequestError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const queryToken = new URLSearchParams(location.search).get("token");
    if (queryToken) {
      setToken(queryToken);
      navigate(location.pathname, { replace: true });
    }
  }, [location.pathname, location.search, navigate]);

  async function accept() {
    if (!token) return;
    setSubmitting(true);
    setRequestError(null);
    try {
      await workspaceApi.acceptInvitation(token);
      setToken(null);
      setSuccess(true);
    } catch (error) {
      setRequestError(invitationError(error));
    } finally {
      setSubmitting(false);
    }
  }

  function cancel() {
    setToken(null);
    setRequestError(null);
    navigate("/app", { replace: true });
  }

  const loginState = {
    from: {
      pathname: "/accept-invitation",
      search: token ? `?token=${encodeURIComponent(token)}` : "",
    },
  };

  return (
    <AuthLayout>
      <div className="form-heading">
        <p className="eyebrow">WORKSPACE INVITATION</p>
        <h1>Join a workspace</h1>
        <p>Accept the invitation using the account whose email address was invited.</p>
      </div>
      {loading ? (
        <p role="status">Checking your account…</p>
      ) : success ? (
        <>
          <p className="success-banner" role="status">
            Invitation accepted. You can now open the workspace in TeamFlow.
          </p>
          <Link to="/app">Continue to TeamFlow</Link>
        </>
      ) : !token ? (
        <>
          <p className="error-banner" role="alert">
            The invitation token is missing. Reopen the complete invitation link.
          </p>
          <Link to="/app">Return to TeamFlow</Link>
        </>
      ) : !user ? (
        <>
          <p role="status">Sign in with the invited email address to continue.</p>
          <Link to="/login" state={loginState}>Sign in</Link>
          <Link to="/register" state={loginState}>Create an account</Link>
          <button className="quiet-button" onClick={cancel} type="button">
            Cancel invitation
          </button>
        </>
      ) : (
        <>
          <p role="status">Signed in as {user.email}</p>
          {requestError && <p className="error-banner" role="alert">{requestError}</p>}
          <button
            className="primary-button"
            disabled={submitting}
            onClick={() => void accept()}
            type="button"
          >
            {submitting ? "Accepting invitation…" : "Accept invitation"}
          </button>
          <button className="quiet-button" onClick={cancel} type="button">
            Cancel
          </button>
        </>
      )}
    </AuthLayout>
  );
}
