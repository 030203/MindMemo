import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { ProtectedRoute } from "./components/auth/ProtectedRoute";
import { AppShell } from "./components/layout/AppShell";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HomePage } from "./pages/HomePage";
import { InboxPage } from "./pages/InboxPage";
import { InsightsPage } from "./pages/InsightsPage";
import { MemoriesPage } from "./pages/MemoriesPage";
import { MemoryDetailPage } from "./pages/MemoryDetailPage";
import { MemoryManagerPage } from "./pages/MemoryManagerPage";
import { RemindersPage } from "./pages/RemindersPage";
import { ReviewPage } from "./pages/ReviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ChatPage } from "./pages/ChatPage";
import { TodosPage } from "./pages/TodosPage";

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
        <Route path="inbox" element={<InboxPage />} />
        <Route path="memories" element={<MemoriesPage />} />
        <Route path="memories/:memoryId" element={<MemoryDetailPage />} />
        <Route path="todos" element={<TodosPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="reminders" element={<RemindersPage />} />
        <Route path="insights" element={<InsightsPage />} />
        <Route path="memory-manager" element={<MemoryManagerPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
