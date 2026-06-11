import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthProvider";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const auth = useAuth();

  if (auth.status === "loading") {
    return (
      <div className="auth-loading-shell">
        <div className="panel auth-loading-card">
          <h3>正在确认登录状态</h3>
          <p className="panel-subtitle">马上就好，正在帮你打开自己的记录空间。</p>
        </div>
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return <Navigate to="/auth" replace />;
  }

  return <>{children}</>;
}
