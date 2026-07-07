export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface UserProfile {
  id: string;
  display_name: string;
  email: string | null;
}

export interface AuthResponseData {
  access_token: string;
  refresh_token: string;
  user_profile: UserProfile;
}

export interface UserRegisterRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface UserLoginRequest {
  account: string;
  password: string;
}

export interface UserProfileUpdateRequest {
  display_name: string;
  email: string;
}

export interface DashboardOverview {
  today_focus: string;
  today_todos: number;
  overdue_todos: number;
  recent_memories: number;
  pending_reviews: number;
  daily_summary: string;
}

export interface ReminderItem {
  id: string;
  type: string;
  level: string;
  title: string;
  message: string;
  todo_id: string;
  due_at: string | null;
}

export interface MemoryItem {
  id: string;
  title: string;
  source_type: string;
  source_url: string | null;
  file_name: string | null;
  content_summary: string;
  category: string;
  tags: string[];
  importance_score: number;
  event_time: string | null;
  due_time: string | null;
  status: string;
}

export interface MemoryDetail extends MemoryItem {
  content_raw: string;
  keywords: string[];
  entities: string[];
}

export interface MemoryCreateRequest {
  title: string;
  content: string;
  category: string;
  source_type: string;
  run_ai_parse?: boolean;
  source_url?: string | null;
  file_name?: string | null;
  source_mime_type?: string | null;
}

export interface UrlIngestRequest {
  url: string;
  title?: string;
  category: string;
}

export interface TextIngestRequest {
  content: string;
  title?: string;
  record_type: "memo" | "todo" | "reminder";
  due_at?: string | null;
  remind_at?: string | null;
}

export interface TextIngestResult {
  memory_id: string | null;
  todo_id: string | null;
  record_type: string;
}

export interface MemoryUpdateRequest {
  title: string;
  content: string;
  category: string;
}

export interface MemoryListQuery {
  q?: string;
  category?: string;
}

export interface TodoItem {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  due_at: string | null;
  risk_level: string;
  source_memory_id?: string | null;
}

export interface TodoCreateRequest {
  title: string;
  description: string;
  priority: string;
  due_at: string | null;
  source_memory_id?: string | null;
}

export interface TodoUpdateRequest {
  title: string;
  description: string;
  priority: string;
  status: string;
  due_at: string | null;
  source_memory_id?: string | null;
}

export interface TodoListQuery {
  q?: string;
  status?: string;
  priority?: string;
  sort?: "priority" | "newest" | "due";
}

export interface TimelineItem {
  id: string;
  title: string;
  summary: string;
  event_type: string;
  event_time: string;
}

export interface QAResponse {
  answer: string;
}

export interface ReviewItem {
  id: string;
  review_type: string;
  reason: string;
  target_title: string;
  status: string;
}

export interface SettingsData {
  timezone: string;
  notify_channels: string[];
}

export interface SettingsUpdateRequest {
  notify_channels?: string[];
}

export interface NotificationProviderStatus {
  channel: string;
  configured: boolean;
}

export interface NotificationTestResponse {
  channel: string;
  sent: boolean;
}

export interface InsightItem {
  id: string;
  insight_type: string;
  title: string;
  content: string;
  confidence: number;
  created_at: string | null;
}

export interface InsightGenerateResponse {
  status: string;
  insight?: InsightItem;
  message?: string;
}

export interface MaintenanceReport {
  duplicates_found: number;
  decayed_memories: number;
  expired_insights: number;
  users_processed: number;
}

export interface AdminMeResponse {
  last_maintenance_at: string | null;
}

// ────────────────────────────────────────────────────────────
// Chat / Session
// ────────────────────────────────────────────────────────────

export interface ChatSessionCreateRequest {
  context_type: "global" | "memory" | "todo";
  context_id?: string | null;
  title?: string | null;
}

export interface ChatSessionResponse {
  session_id: string;
  context_type: string;
  context_id: string | null;
  title: string | null;
  created_at: string;
  pinned: boolean;
}

export interface ChatMessageItem {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface SessionQARequest {
  question: string;
}

export interface SessionQAResponse {
  answer: string;
  session_id: string;
  message_id: string;
}
