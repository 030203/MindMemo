import type {
  ApiResponse,
  AgentRun,
  AuthResponseData,
  DashboardInsights,
  DashboardOverview,
  MemoryInsightCard,
  MemoryCreateRequest,
  MemoryDetail,
  MemoryItem,
  MemoryListQuery,
  MemoryRelatedItem,
  MemorySignalItem,
  MemoryUpdateRequest,
  NotificationProviderStatus,
  NotificationTestResponse,
  QARequest,
  QAResponseData,
  RetrievalTraceResponse,
  ReminderItem,
  ReviewItem,
  SettingsData,
  SettingsUpdateRequest,
  TimelineItem,
  TodoCreateRequest,
  TodoItem,
  TodoListQuery,
  TodoUpdateRequest,
  UrlIngestRequest,
  UserLoginRequest,
  UserProfile,
  UserProfileUpdateRequest,
  UserRegisterRequest,
  WeatherRequest,
  WeatherResponse,
  WebSearchRequest,
  WebSearchResponse,
} from "./types";
import {
  clearAuthSession,
  getStoredAccessToken,
  loadAuthSession,
  saveAuthSession,
  toStoredAuthSession,
} from "../auth/session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:6200/api/v1";

let refreshRequest: Promise<string | null> | null = null;

async function sendRequest(path: string, init?: RequestInit, accessToken?: string | null) {
  const isFormDataBody = typeof FormData !== "undefined" && init?.body instanceof FormData;

  return fetch(`${API_BASE_URL}${path}`, {
    headers: {
      ...(isFormDataBody ? {} : { "Content-Type": "application/json" }),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(init?.headers ?? {}),
    },
    ...init,
  });
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;

    try {
      const errorPayload = (await response.json()) as { detail?: string; message?: string };
      message = errorPayload.detail ?? errorPayload.message ?? message;
    } catch {
      // ignore parse failure and fall back to status text
    }

    throw new Error(message);
  }

  const payload = (await response.json()) as ApiResponse<T>;

  if (payload.code !== 0) {
    throw new Error(payload.message || "Request failed");
  }

  return payload.data;
}

function redirectToAuth() {
  clearAuthSession();
  if (!window.location.pathname.startsWith("/auth")) {
    window.location.replace("/auth");
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const session = loadAuthSession();
  if (!session?.refreshToken) {
    return null;
  }

  if (!refreshRequest) {
    refreshRequest = sendRequest("/auth/refresh", {
      method: "POST",
      body: JSON.stringify({ refresh_token: session.refreshToken }),
    })
      .then(async (response) => {
        const data = await parseResponse<AuthResponseData>(response);
        const nextSession = toStoredAuthSession(data);
        saveAuthSession(nextSession);
        return nextSession.accessToken;
      })
      .catch(() => {
        redirectToAuth();
        return null;
      })
      .finally(() => {
        refreshRequest = null;
      });
  }

  return refreshRequest;
}

async function request<T>(path: string, init?: RequestInit, canRetry = true): Promise<T> {
  const accessToken = getStoredAccessToken();
  const hasStoredSession = Boolean(loadAuthSession());
  const response = await sendRequest(path, init, accessToken);

  if (response.status === 401 && hasStoredSession && canRetry && path !== "/auth/refresh") {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      const retriedResponse = await sendRequest(path, init, refreshedToken);
      if (retriedResponse.status === 401) {
        redirectToAuth();
      }
      return parseResponse<T>(retriedResponse);
    }
  }

  if (response.status === 401 && hasStoredSession) {
    redirectToAuth();
  }

  return parseResponse<T>(response);
}

function withQuery(path: string, query?: Record<string, string | undefined>) {
  if (!query) {
    return path;
  }

  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value && value.trim()) {
      params.set(key, value.trim());
    }
  });

  const serialized = params.toString();
  return serialized ? `${path}?${serialized}` : path;
}

export const api = {
  register: (payload: UserRegisterRequest) =>
    request<AuthResponseData>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  login: (payload: UserLoginRequest) =>
    request<AuthResponseData>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getMe: () => request<UserProfile>("/auth/me"),
  updateMe: (payload: UserProfileUpdateRequest) =>
    request<UserProfile>("/auth/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  getDashboardOverview: () => request<DashboardOverview>("/dashboard/overview"),
  getDashboardInsights: () => request<DashboardInsights>("/dashboard/insights"),
  getDashboardReminders: (limit?: number) => request<ReminderItem[]>(withQuery("/dashboard/reminders", limit ? { limit: String(limit) } : undefined)),
  getInsightOverview: (window?: string) => request<DashboardInsights>(withQuery("/insights/overview", window ? { window } : undefined)),
  getExpenseInsights: (window?: string) => request<DashboardInsights>(withQuery("/insights/expenses", window ? { window } : undefined)),
  getReflectionInsights: (window?: string) => request<DashboardInsights>(withQuery("/insights/reflection", window ? { window } : undefined)),
  getInsightCard: (kind: string, window?: string) => request<MemoryInsightCard>(withQuery(`/insights/${kind}`, window ? { window } : undefined)),
  listMemories: (query?: MemoryListQuery) =>
    request<MemoryItem[]>(withQuery("/memories", query as Record<string, string | undefined> | undefined)),
  getMemoryDetail: (memoryId: string) => request<MemoryDetail>(`/memories/${memoryId}`),
  listRelatedMemories: (memoryId: string) => request<MemoryRelatedItem[]>(`/memories/${memoryId}/related`),
  createMemory: (payload: MemoryCreateRequest) =>
    request<MemoryDetail>("/memories", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ingestUrl: (payload: UrlIngestRequest) =>
    request<MemoryDetail>("/ingest/url", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ingestPdf: (payload: FormData) =>
    request<MemoryDetail>("/ingest/pdf", {
      method: "POST",
      body: payload,
    }),
  ingestDocument: (payload: FormData) =>
    request<MemoryDetail>("/ingest/document", {
      method: "POST",
      body: payload,
    }),
  ingestImage: (payload: FormData) =>
    request<MemoryDetail>("/ingest/image", {
      method: "POST",
      body: payload,
    }),
  updateMemory: (memoryId: string, payload: MemoryUpdateRequest) =>
    request<MemoryDetail>(`/memories/${memoryId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteMemory: (memoryId: string) =>
    request<{ deleted: boolean }>(`/memories/${memoryId}`, {
      method: "DELETE",
    }),
  listTodos: (query?: TodoListQuery) =>
    request<TodoItem[]>(withQuery("/todos", query as Record<string, string | undefined> | undefined)),
  createTodo: (payload: TodoCreateRequest) =>
    request<TodoItem>("/todos", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateTodo: (todoId: string, payload: TodoUpdateRequest) =>
    request<TodoItem>(`/todos/${todoId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  completeTodo: (todoId: string) =>
    request<TodoItem>(`/todos/${todoId}/complete`, {
      method: "POST",
    }),
  deleteTodo: (todoId: string) =>
    request<{ deleted: boolean }>(`/todos/${todoId}`, {
      method: "DELETE",
    }),
  listTimeline: () => request<TimelineItem[]>("/timeline"),
  listMemorySignals: (factType?: string) =>
    request<MemorySignalItem[]>(withQuery("/timeline/signals", factType ? { fact_type: factType } : undefined)),
  askQuestion: (payload: QARequest) =>
    request<QAResponseData>("/qa/ask", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listRetrievalTraces: (limit = 20) => request<RetrievalTraceResponse[]>(`/qa/traces?limit=${limit}`),
  listAgentRuns: (limit = 20) => request<AgentRun[]>(`/qa/agent-runs?limit=${limit}`),
  webSearch: (payload: WebSearchRequest) =>
    request<WebSearchResponse>("/tools/web-search", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getWeather: (payload: WeatherRequest) =>
    request<WeatherResponse>("/tools/weather", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listReviews: () => request<ReviewItem[]>("/review-queue"),
  confirmReview: (reviewId: string) =>
    request<ReviewItem>(`/review-queue/${reviewId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ note: "" }),
    }),
  ignoreReview: (reviewId: string) =>
    request<ReviewItem>(`/review-queue/${reviewId}/ignore`, {
      method: "POST",
      body: JSON.stringify({ note: "" }),
    }),
  convertReviewToTodo: (reviewId: string) =>
    request<ReviewItem>(`/review-queue/${reviewId}/convert-to-todo`, {
      method: "POST",
      body: JSON.stringify({ note: "" }),
    }),
  getSettings: () => request<SettingsData>("/settings"),
  updateSettings: (payload: SettingsUpdateRequest) =>
    request<SettingsData>("/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  getNotificationProviders: () => request<NotificationProviderStatus[]>("/settings/notification-providers"),
  testNotification: (channel: string) =>
    request<NotificationTestResponse>("/settings/notifications/test", {
      method: "POST",
      body: JSON.stringify({ channel }),
    }),
};
