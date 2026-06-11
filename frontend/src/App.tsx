import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { ProtectedRoute } from "./components/auth/ProtectedRoute";
import { AppShell } from "./components/layout/AppShell";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HomePage } from "./pages/HomePage";
import { MemoryDetailPage } from "./pages/MemoryDetailPage";
import { SettingsPage } from "./pages/SettingsPage";

function LegacyMemoryRedirect() {
  const { memoryId } = useParams();

  if (!memoryId) {
    return <Navigate to="/app" replace />;
  }

  return <Navigate to={`/app/memories/${memoryId}`} replace />;
}

function LegacySettingsRedirect() {
  return <Navigate to="/app/settings" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/auth" element={<AuthPage />} />
      <Route path="/settings" element={<LegacySettingsRedirect />} />
      <Route path="/memories/:memoryId" element={<LegacyMemoryRedirect />} />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="memories/:memoryId" element={<MemoryDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
