import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AuthResponseData, UserProfile } from "../api/types";
import { clearAuthSession, loadAuthSession, saveAuthSession, toStoredAuthSession } from "./session";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  isAuthenticated: boolean;
  user: UserProfile | null;
  applyAuthResponse: (payload: AuthResponseData) => void;
  updateUser: (profile: UserProfile) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserProfile | null>(null);

  useEffect(() => {
    const session = loadAuthSession();

    if (!session) {
      setStatus("unauthenticated");
      setUser(null);
      return;
    }

    setUser(session.userProfile);

    api
      .getMe()
      .then((profile) => {
        saveAuthSession({
          ...session,
          userProfile: profile,
        });
        setUser(profile);
        setStatus("authenticated");
      })
      .catch(() => {
        clearAuthSession();
        setUser(null);
        setStatus("unauthenticated");
      });
  }, []);

  function applyAuthResponse(payload: AuthResponseData) {
    const session = toStoredAuthSession(payload);
    saveAuthSession(session);
    setUser(session.userProfile);
    setStatus("authenticated");
  }

  function updateUser(profile: UserProfile) {
    const session = loadAuthSession();
    if (session) {
      saveAuthSession({
        ...session,
        userProfile: profile,
      });
    }
    queryClient.setQueryData(["me"], profile);
    setUser(profile);
  }

  function logout() {
    clearAuthSession();
    queryClient.clear();
    setUser(null);
    setStatus("unauthenticated");
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      isAuthenticated: status === "authenticated",
      user,
      applyAuthResponse,
      updateUser,
      logout,
    }),
    [status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within AuthProvider");
  }

  return value;
}
