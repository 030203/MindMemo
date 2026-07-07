# Spec: 对话上下文感知 & 会话持久化

**版本**: v1.0  
**日期**: 2026-06-30  
**范围**: 后端会话存储 + QA 问答上下文注入 + 前端记录关联问答

---

## 1. 背景与目标

### 当前问题

1. **无上下文感知**：每次调用 `/api/v1/qa/ask` 都是无状态的——用户选中一条记录问 "这条是什么意思？" 后再问 "能展开说说吗？"，AI 不知道 "这条" 和 "展开" 指的什么
2. **无会话记忆**：聊天记录只存在前端 React state，刷新即丢失，多标签页不同步
3. **无短期感知**：QA Workflow 的 `history` 参数虽然存在，但 API 层没有传入任何历史消息

### 目标

| 目标 | 说明 |
|------|------|
| 记录上下文注入 | 用户选中某条记录发起问答时，AI 能读到该记录的完整内容 |
| 短期会话记忆 | 同一会话内的多轮对话历史随每次请求传给 LLM |
| 会话持久化 | 会话消息保存在服务端（SQLite），刷新后可恢复 |
| 多会话隔离 | 每个记录/全局 AI 有独立会话 ID，互不干扰 |

---

## 2. 存储选型

**选 SQLite（现有数据库），不引入 Redis。**

理由：
- 项目当前已用 SQLite，零新依赖
- 会话数据读写频率低（QPS < 10），不需要 Redis 的高吞吐
- 会话历史需要持久化（不能丢），SQLite ACID 保证优于内存缓存
- Redis 需要额外部署和配置，增加运维负担

只有在并发用户量 > 100、或需要跨进程共享会话时才值得引入 Redis。

---

## 3. 数据模型

### 3.1 新增表：`chat_sessions`

```sql
CREATE TABLE chat_sessions (
    id          TEXT PRIMARY KEY,          -- UUID，会话 ID
    user_id     TEXT NOT NULL,             -- 外键 users.id
    context_type TEXT NOT NULL DEFAULT 'global',  -- 'global' | 'memory' | 'todo'
    context_id  TEXT,                      -- 关联的 memory_id 或 todo_id（可空）
    title       TEXT,                      -- 会话标题，取自记录标题或"全局对话"
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    deleted_at  DATETIME                   -- 软删除
);
```

### 3.2 新增表：`chat_messages`

```sql
CREATE TABLE chat_messages (
    id          TEXT PRIMARY KEY,          -- UUID
    session_id  TEXT NOT NULL,             -- 外键 chat_sessions.id
    role        TEXT NOT NULL,             -- 'user' | 'assistant' | 'system'
    content     TEXT NOT NULL,
    created_at  DATETIME NOT NULL
);
```

### 3.3 SQLAlchemy 模型（`backend/app/models/chat.py`）

```python
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    context_type = Column(String, nullable=False, default="global")
    context_id = Column(String, nullable=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime, nullable=True)

    messages = relationship("ChatMessage", back_populates="session",
                            order_by="ChatMessage.created_at")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    session = relationship("ChatSession", back_populates="messages")
```

---

## 4. 后端 API 设计

### 4.1 新增端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/chat/sessions` | 创建或获取会话（幂等，按 context 查找已有） |
| `GET` | `/api/v1/chat/sessions/{session_id}/messages` | 拉取历史消息 |
| `POST` | `/api/v1/chat/sessions/{session_id}/ask` | 带上下文的问答（替代 `/qa/ask`） |
| `DELETE` | `/api/v1/chat/sessions/{session_id}` | 软删除会话 |

### 4.2 请求/响应 Schema

#### `POST /chat/sessions` — 创建/获取会话

```python
class ChatSessionCreateRequest(BaseModel):
    context_type: str = "global"      # "global" | "memory" | "todo"
    context_id: str | None = None     # memory_id 或 todo_id
    title: str | None = None

class ChatSessionResponse(BaseModel):
    session_id: str
    context_type: str
    context_id: str | None
    title: str | None
    created_at: datetime
```

逻辑：先查找该用户同 `context_type + context_id` 的活跃会话，存在则返回，不存在则创建。

#### `GET /chat/sessions/{session_id}/messages`

```python
class ChatMessageResponse(BaseModel):
    id: str
    role: str          # "user" | "assistant"
    content: str
    created_at: datetime

# Response: ApiResponse[list[ChatMessageResponse]]
```

#### `POST /chat/sessions/{session_id}/ask` — 核心端点

```python
class SessionQARequest(BaseModel):
    question: str

class SessionQAResponse(BaseModel):
    answer: str
    session_id: str
    message_id: str    # 本次 assistant 消息的 ID
    route: QARouteInfo | None = None
    sources: list[QASourceInfo] = []
```

---

## 5. QA Workflow 上下文注入

### 5.1 修改 `QAWorkflow.run()` 签名

```python
async def run(
    self,
    question: str,
    history: list[dict] | None = None,
    context_doc: str | None = None,      # 新增：记录全文
    user_id: UUID | None = None,
    db: Session | None = None,
) -> dict:
```

`context_doc` 在进入 fast/slow 路径前注入到 history 的 `system` 角色：

```python
effective_history = list(history or [])
if context_doc:
    effective_history.insert(0, {
        "role": "system",
        "content": f"以下是用户正在查看的记录内容，请结合此内容回答用户的问题：\n\n{context_doc}"
    })
```

### 5.2 会话 Service（`backend/app/services/chat_service.py`）

```python
class ChatService:
    HISTORY_WINDOW = 20  # 最多传给 LLM 的历史消息条数

    def get_or_create_session(
        self, db, user_id, context_type, context_id, title
    ) -> ChatSession:
        # 查找已有活跃会话
        existing = chat_repo.find_active(db, user_id, context_type, context_id)
        if existing:
            return existing
        return chat_repo.create(db, ChatSession(
            user_id=str(user_id),
            context_type=context_type,
            context_id=context_id,
            title=title,
        ))

    def get_history_window(self, db, session_id) -> list[dict]:
        """取最近 HISTORY_WINDOW 条，转为 LLM messages 格式"""
        messages = chat_repo.list_messages(db, session_id, limit=self.HISTORY_WINDOW)
        return [{"role": m.role, "content": m.content} for m in messages]

    def append_exchange(self, db, session_id, question, answer):
        """存用户消息 + AI 回答"""
        chat_repo.add_message(db, session_id, role="user", content=question)
        msg = chat_repo.add_message(db, session_id, role="assistant", content=answer)
        return msg

    def build_context_doc(self, db, user_id, context_type, context_id) -> str | None:
        """根据 context 类型拉取记录全文"""
        if context_type == "memory" and context_id:
            mem = memory_repo.get_for_user(db, user_id, context_id)
            if mem:
                return f"标题：{mem.title}\n\n{mem.content or ''}"
        if context_type == "todo" and context_id:
            todo = todo_repo.get_for_user(db, user_id, context_id)
            if todo:
                parts = [f"待办标题：{todo.title}"]
                if todo.description:
                    parts.append(f"描述：{todo.description}")
                if todo.due_at:
                    parts.append(f"截止时间：{todo.due_at.isoformat()}")
                return "\n".join(parts)
        return None
```

### 5.3 API Handler

```python
@router.post("/sessions/{session_id}/ask")
async def ask_in_session(
    session_id: str,
    payload: SessionQARequest,
    db: Session = Depends(get_db),
    user_id = Depends(get_current_user_id),
) -> ApiResponse[SessionQAResponse]:
    session = chat_service.get_session_for_user(db, user_id, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    history = chat_service.get_history_window(db, session_id)
    context_doc = chat_service.build_context_doc(
        db, user_id, session.context_type, session.context_id
    )

    result = await qa_workflow.run(
        question=payload.question,
        history=history,
        context_doc=context_doc,
        user_id=user_id,
        db=db,
    )

    msg = chat_service.append_exchange(db, session_id, payload.question, result["answer"])
    return ApiResponse(data=SessionQAResponse(
        answer=result["answer"],
        session_id=session_id,
        message_id=str(msg.id),
        route=...,
        sources=...,
    ))
```

---

## 6. 前端改动

### 6.1 状态管理变化

| 当前状态 | 改后状态 |
|---------|---------|
| `chatMessages` 存在 React state，刷新丢失 | 初始化时从 `/chat/sessions/{id}/messages` 拉取历史 |
| `selectedContext` 只是前端 FeedItem 对象 | 打开 AI 面板时先调 `POST /chat/sessions` 获取 `session_id` |
| `submitQuestion` 调 `/qa/ask` | 改为调 `/chat/sessions/{session_id}/ask` |

### 6.2 打开 AI 面板的流程

```
用户点击某条记录的 AI 按钮
  → POST /chat/sessions { context_type: "memory", context_id: item.memoryId, title: item.title }
  → 后端返回 session_id（复用或新建）
  → GET /chat/sessions/{session_id}/messages
  → 渲染历史消息
  → 用户输入 → POST /chat/sessions/{session_id}/ask
```

全局 AI（无记录上下文）：`context_type: "global"`, `context_id: null`

### 6.3 新增 API client 方法

```typescript
// 在 client.ts 新增
createOrGetSession: (payload: ChatSessionCreateRequest) =>
  request<ChatSessionResponse>("/chat/sessions", { method: "POST", body: JSON.stringify(payload) }),

getSessionMessages: (sessionId: string) =>
  request<ChatMessageResponse[]>(`/chat/sessions/${sessionId}/messages`),

askInSession: (sessionId: string, payload: SessionQARequest) =>
  request<SessionQAResponse>(`/chat/sessions/${sessionId}/ask`, {
    method: "POST",
    body: JSON.stringify(payload),
  }),
```

### 6.4 新增 TypeScript 类型（`api/types.ts`）

```typescript
export type ChatSessionCreateRequest = {
  context_type: "global" | "memory" | "todo";
  context_id?: string | null;
  title?: string | null;
};

export type ChatSessionResponse = {
  session_id: string;
  context_type: string;
  context_id: string | null;
  title: string | null;
  created_at: string;
};

export type ChatMessageResponse = {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type SessionQARequest = {
  question: string;
};

export type SessionQAResponse = {
  answer: string;
  session_id: string;
  message_id: string;
  route?: { complexity: string; reason: string };
  sources?: Array<{ memory_id: string; title: string }>;
};
```

---

## 7. 实施步骤（按顺序）

| 步骤 | 文件 | 说明 |
|------|------|------|
| 1 | `backend/app/models/chat.py` | 新增 ChatSession、ChatMessage 模型 |
| 2 | `backend/app/models/__init__.py` | 注册新模型到 Base.metadata |
| 3 | `backend/app/repos/chat_repo.py` | CRUD：find_active, create, list_messages, add_message, get_session |
| 4 | `backend/app/services/chat_service.py` | 业务逻辑：get_or_create_session, get_history_window, append_exchange, build_context_doc |
| 5 | `backend/app/schemas/chat.py` | Pydantic schema |
| 6 | `backend/app/api/v1/chat.py` | 路由：POST /sessions, GET /sessions/{id}/messages, POST /sessions/{id}/ask, DELETE /sessions/{id} |
| 7 | `backend/app/api/router.py` | 注册 `/chat` 路由 |
| 8 | `backend/app/orchestration/qa_workflow.py` | `run()` 加 `context_doc` 参数，注入 system message |
| 9 | `frontend/src/api/types.ts` | 新增 Chat 相关类型 |
| 10 | `frontend/src/api/client.ts` | 新增 3 个 API 方法 |
| 11 | `frontend/src/pages/DashboardPage.tsx` | 重构 `openAiForItem` 和 `submitQuestion`，接入会话 API |

---

## 8. 历史消息截断策略

传给 LLM 的消息窗口：**最近 20 条**（user + assistant 交替）

超出部分静默丢弃（不做摘要）。20 条约等于 10 轮对话，足够短期上下文感知，同时控制 token 消耗。

如需升级：可在 20 条之外额外附加一条 system 摘要（Phase 2 再做）。

---

## 9. 不在本 spec 范围内

- 会话摘要压缩（超长对话自动摘要）
- 会话列表 UI（查看历史会话）
- 跨设备实时同步（WebSocket）
- Redis 迁移

---

## 10. 文件清单

```
backend/app/models/chat.py          ← 新增
backend/app/repos/chat_repo.py      ← 新增
backend/app/services/chat_service.py ← 新增
backend/app/schemas/chat.py         ← 新增
backend/app/api/v1/chat.py          ← 新增
backend/app/models/__init__.py      ← 修改（注册模型）
backend/app/api/router.py           ← 修改（注册路由）
backend/app/orchestration/qa_workflow.py ← 修改（context_doc 参数）
frontend/src/api/types.ts           ← 修改（新增类型）
frontend/src/api/client.ts          ← 修改（新增方法）
frontend/src/pages/DashboardPage.tsx ← 修改（接入会话 API）
```
