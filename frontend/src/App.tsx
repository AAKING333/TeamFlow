import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import { LoadingMessage, RequestError } from "./components/AuthUi";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AppShell } from "./pages/AppShell";
import { AcceptInvitationPage } from "./pages/AcceptInvitationPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";

function HomeRoute() {
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
  return <Navigate to={user ? "/app" : "/login"} replace />;
}

export function App() {
  const { loading } = useAuth();
  return (
    <Routes>
      <Route path="/" element={<HomeRoute />} />
      <Route
        path="/login"
        element={loading ? <LoadingMessage /> : <LoginPage />}
      />
      <Route
        path="/register"
        element={loading ? <LoadingMessage /> : <RegisterPage />}
      />
      <Route path="/accept-invitation" element={<AcceptInvitationPage />} />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
