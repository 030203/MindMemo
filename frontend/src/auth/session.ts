import type { AuthResponseData, UserProfile } from "../api/types";

const AUTH_STORAGE_KEY = "mindmemo.auth";

export interface StoredAuthSession {
  accessToken: string;
  refreshToken: string;
  userProfile: UserProfile;
}

export function toStoredAuthSession(payload: AuthResponseData): StoredAuthSession {
  return {
    accessToken: payload.access_token,
    refreshToken: payload.refresh_token,
    userProfile: payload.user_profile,
  };
}

export function loadAuthSession(): StoredAuthSession | null {
  const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<StoredAuthSession>;
    if (!parsed.accessToken || !parsed.refreshToken || !parsed.userProfile) {
      return null;
    }

    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken,
      userProfile: parsed.userProfile,
    };
  } catch {
    return null;
  }
}

export function saveAuthSession(session: StoredAuthSession) {
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
}

export function clearAuthSession() {
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

export function getStoredAccessToken() {
  return loadAuthSession()?.accessToken ?? null;
}

export function getStoredRefreshToken() {
  return loadAuthSession()?.refreshToken ?? null;
}
