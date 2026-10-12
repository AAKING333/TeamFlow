import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { LoadingMessage, RequestError } from "./AuthUi";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const location = useLocation();
  const { user, loading, loadError } = useAuth();

  if (loading) return <LoadingMessage />;
  if (loadError) {
    return (
      <main className="centered-page">
        <RequestError>{loadError}</RequestError>
        <p>Refresh the page to retry loading your account.</p>
      </main>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}
