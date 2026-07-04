import type {
  AdminMeResponse,
  ApiResponse,
  AuthResponseData,
  ChatMessageItem,
  ChatSessionCreateRequest,
  ChatSessionResponse,
  DashboardOverview,
  InsightGenerateResponse,
  InsightItem,
  MaintenanceReport,
  MemoryCreateRequest,
  MemoryDetail,
  MemoryItem,
  MemoryListQuery,
  MemoryUpdateRequest,
  NotificationProviderStatus,
  NotificationTestResponse,
  QAResponse,
  ReminderItem,
  ReviewItem,
  SessionQARequest,
  SessionQAResponse,
  SettingsData,
  SettingsUpdateRequest,
  TextIngestRequest,
  TextIngestResult,
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
  getDashboardReminders: (limit?: number) => request<ReminderItem[]>(withQuery("/dashboard/reminders", limit ? { limit: String(limit) } : undefined)),
  listMemories: (query?: MemoryListQuery) =>
    request<MemoryItem[]>(withQuery("/memories", query as Record<string, string | undefined> | undefined)),
  getMemoryDetail: (memoryId: string) => request<MemoryDetail>(`/memories/${memoryId}`),
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
  ingestText: (payload: TextIngestRequest) =>
    request<TextIngestResult>("/ingest/text", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  ingestCapture: (payload: FormData) =>
    request<TextIngestResult>("/ingest/capture", {
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
  askQuestion: (payload: { question: string }) =>
    request<QAResponse>("/qa/ask", {
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
  listInsights: (days?: number) =>
    request<InsightItem[]>(withQuery("/insights/", days ? { days: String(days) } : undefined)),
  generateInsight: () =>
    request<InsightGenerateResponse>("/insights/generate", {
      method: "POST",
    }),
  runMaintenance: () =>
    request<MaintenanceReport>("/admin/run-maintenance", {
      method: "POST",
    }),
  getAdminMe: () => request<AdminMeResponse>("/admin/me"),

  // ── Chat / Session ──────────────────────────────────────
  listSessions: () => request<ChatSessionResponse[]>("/chat/sessions"),
  createOrGetSession: (payload: ChatSessionCreateRequest) =>
    request<ChatSessionResponse>("/chat/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSessionMessages: (sessionId: string) =>
    request<ChatMessageItem[]>(`/chat/sessions/${sessionId}/messages`),
  askInSession: (sessionId: string, payload: SessionQARequest) =>
    request<SessionQAResponse>(`/chat/sessions/${sessionId}/ask`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  askInSessionStream: (
    sessionId: string,
    payload: SessionQARequest,
    onChunk: (content: string) => void,
    onDone: (messageId: string) => void,
    onError: (error: string) => void,
    signal?: AbortSignal,
  ) => {
    const accessToken = getStoredAccessToken();
    const url = `${API_BASE_URL}/chat/sessions/${sessionId}/ask-stream`;

    // 打字机渲染：把服务端推来的每个 chunk（可能是几个字的一小段）拆成
    // 单个字符，用定时器逐字吐给 onChunk，形成"一字一字"的效果。
    // 无论上游是 LLM 的 token 流还是编排层的整段，前端表现一致。
    const TYPE_INTERVAL_MS = 16; // 每字间隔，约 60 字/秒
    const charQueue: string[] = []; // 按码点入队，避免拆断 emoji / 代理对
    let streamEnded = false; // 网络流是否已结束
    let flushed = false; // onDone/onError 是否已回调，防重复
    let pendingMessageId = "";
    let pendingError: string | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;

    const stopTimer = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    const finish = () => {
      if (flushed) return;
      flushed = true;
      stopTimer();
      if (pendingError !== null) onError(pendingError);
      else onDone(pendingMessageId);
    };

    const ensureTimer = () => {
      if (timer !== null) return;
      timer = setInterval(() => {
        if (signal?.aborted) {
          charQueue.length = 0;
          stopTimer();
          return;
        }
        const ch = charQueue.shift();
        if (ch !== undefined) {
          onChunk(ch);
          return;
        }
        // 队列排空：流已结束则收尾，否则暂停等新数据
        if (streamEnded) finish();
        else stopTimer();
      }, TYPE_INTERVAL_MS);
    };

    const enqueue = (text: string) => {
      if (!text) return;
      // Array.from 按 Unicode 码点拆分，emoji / 组合字符不会被截断
      for (const ch of Array.from(text)) charQueue.push(ch);
      ensureTimer();
    };

    fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          pendingError = `请求失败: ${response.status}`;
          streamEnded = true;
          finish();
          return;
        }
        const reader = response.body?.getReader();
        if (!reader) {
          pendingError = "响应体不可读";
          streamEnded = true;
          finish();
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed || !trimmed.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(trimmed.slice(6));
              if (data.type === "chunk") {
                enqueue(String(data.content ?? ""));
              } else if (data.type === "done") {
                pendingMessageId = data.message_id ?? "";
              } else if (data.type === "error") {
                pendingError = data.content;
              }
            } catch {
              // skip parse errors
            }
          }
        }

        // 网络流结束：让定时器把剩余字符吐完再收尾；队列已空则直接收尾。
        streamEnded = true;
        if (charQueue.length === 0) finish();
        else ensureTimer();
      })
      .catch((err) => {
        streamEnded = true;
        if (err.name !== "AbortError") {
          pendingError = err.message ?? "网络错误";
          finish();
        } else {
          // 用户中止：清空队列、停止吐字，不再回调
          charQueue.length = 0;
          stopTimer();
        }
      });
  },
  updateSession: (sessionId: string, payload: { title?: string | null; pinned?: boolean }) =>
    request<ChatSessionResponse>(`/chat/sessions/${sessionId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  updateReminder: (reminderId: string, payload: { due_at?: string | null; status?: string }) =>
    request<{ status: string }>(`/dashboard/reminders/${reminderId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteReminder: (reminderId: string) =>
    request<{ status: string }>(`/dashboard/reminders/${reminderId}`, {
      method: "DELETE",
    }),
  deleteSession: (sessionId: string) =>
    request<{ deleted: boolean }>(`/chat/sessions/${sessionId}`, {
      method: "DELETE",
    }),
};
