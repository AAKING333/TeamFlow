import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, authApi, type User } from "../api/auth";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  loadError: string | null;
  refreshUser: () => Promise<User | null>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshUser = useCallback(async () => {
    setLoadError(null);
    try {
      const response = await authApi.currentUser();
      setUser(response.user);
      return response.user;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null);
        return null;
      }
      setLoadError(
        error instanceof Error
          ? error.message
          : "TeamFlow could not load your account.",
      );
      throw error;
    }
  }, []);

  useEffect(() => {
    let active = true;
    void authApi
      .currentUser()
      .then((response) => {
        if (active) setUser(response.user);
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          setUser(null);
        } else {
          setLoadError(
            error instanceof Error
              ? error.message
              : "TeamFlow could not load your account.",
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, loadError, refreshUser, logout }),
    [user, loading, loadError, refreshUser, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider.");
  }
  return context;
}
