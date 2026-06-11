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

export interface MemoryInsightCard {
  kind: string;
  title: string;
  value: string;
  detail: string;
  tone: string;
  items: string[];
  question: string;
  sources: InsightSourceItem[];
}

export interface DashboardInsights {
  cards: MemoryInsightCard[];
}

export interface InsightSourceItem {
  type: string;
  id: string;
  title: string;
  snippet: string;
  event_time: string | null;
}

export interface ReminderItem {
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
  extracted_facts: ExtractedFact[];
}

export interface MemoryRelatedItem {
  id: string;
  title: string;
  content_summary: string;
  category: string;
  relation_type: string;
  relation_reason: string;
  score: number;
  event_time: string | null;
}

export interface ExtractedFact {
  id: string;
  fact_type: string;
  title: string;
  structured_payload: Record<string, unknown>;
  confidence_score: number;
  event_time: string | null;
  source: string;
}

export interface MemoryCreateRequest {
  title: string;
  content: string;
  category: string;
  source_type: string;
  run_ai_parse: boolean;
  source_url?: string | null;
  file_name?: string | null;
  source_mime_type?: string | null;
}

export interface UrlIngestRequest {
  url: string;
  title?: string;
  category: string;
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

export interface MemorySignalItem {
  id: string;
  memory_id: string;
  fact_type: string;
  title: string;
  summary: string;
  event_time: string;
  confidence_score: number;
  tone: string;
  metadata: Record<string, unknown>;
}

export interface CitationItem {
  type: string;
  id: string;
  title: string;
  snippet: string;
  score: number;
}

export interface QARequest {
  question: string;
  mode: "memory_only" | "hybrid_web";
  conversation_context?: QAContextMessage[];
  context_memory_id?: string;
  context_title?: string;
  context_text?: string;
  active_doc_id?: string;
  active_record_id?: string;
  selected_text?: string;
  visible_page?: number;
  visible_chunk_ids?: string[];
  active_context_type?: "document" | "record" | "none";
}

export interface QAContextMessage {
  role: "user" | "assistant";
  content: string;
}

export interface RetrievalTraceCandidate {
  rank: number;
  memory_id: string;
  chunk_id: string;
  title: string;
  category: string;
  score: number;
  snippet: string;
  raw_hit_score?: number | null;
  normalized_hit_score?: number | null;
  entered_direct_window?: boolean | null;
  entered_rerank?: boolean | null;
  final_selected?: boolean | null;
  exclusion_reason?: string | null;
  exclusion_reason_detail?: string | null;
  citation_source?: string | null;
  final_score?: number | null;
}

export interface CitationScoreBreakdown {
  memory_id: string;
  title: string;
  source: string;
  direct_score: number;
  raw_hit_score?: number | null;
  direct_hit_rank?: number | null;
  relation_score: number;
  recency_score: number;
  fact_score: number;
  source_bonus: number;
  final_score: number;
  relation_reason: string;
  score_formula: string;
  selected?: boolean;
  exclusion_reason?: string;
  exclusion_reason_detail?: string;
  snippet?: string;
  event_time?: string | null;
  category?: string | null;
}

export interface RetrievalTraceResponse {
  id: string;
  question: string;
  mode: "memory_only" | "hybrid_web" | string;
  retrieval_strategy: string;
  answer_source: string;
  candidates: RetrievalTraceCandidate[];
  selected_citations: CitationItem[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AgentRunStep {
  id: string;
  step_index: number;
  key: string;
  label: string;
  status: string;
  detail: string;
  metric: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
}

export interface AgentRun {
  id: string;
  retrieval_trace_id: string | null;
  run_type: string;
  question: string;
  mode: string;
  status: string;
  answer_source: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
  steps: AgentRunStep[];
}

export interface QAResponseData {
  answer: string;
  citations: CitationItem[];
  suggested_followups: string[];
  trace: RetrievalTraceResponse | null;
}

export interface WebSearchRequest {
  query: string;
  max_results?: number;
}

export interface WebSearchResult {
  title: string;
  url: string;
  content: string;
  score: number | null;
}

export interface WebSearchResponse {
  query: string;
  answer: string | null;
  results: WebSearchResult[];
  provider: string;
  configured: boolean;
}

export interface WeatherRequest {
  location: string;
}

export interface WeatherResponse {
  location: string;
  description: string;
  temperature_c: number | null;
  feels_like_c: number | null;
  humidity: number | null;
  wind_speed_mps: number | null;
  provider: string;
  configured: boolean;
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
  llm_provider: string;
  llm_model: string;
  web_search_enabled: boolean;
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
