const categoryMap: Record<string, string> = {
  memo: "随手记",
  learning: "学习记录",
  project: "项目进展",
  idea: "灵感",
  todo: "待办",
};

const todoStatusMap: Record<string, string> = {
  pending: "待处理",
  doing: "进行中",
  done: "已完成",
  blocked: "卡住了",
  cancelled: "已取消",
};

const todoPriorityMap: Record<string, string> = {
  low: "不着急",
  medium: "普通",
  high: "重要",
  urgent: "很急",
};

const reviewTypeMap: Record<string, string> = {
  low_confidence: "需要确认",
  conflict: "信息冲突",
  todo_approval: "待授权",
  relation_confirmation: "关联待确认",
};

const timelineTypeMap: Record<string, string> = {
  memory_created: "新增记录",
  todo_created: "新增待办",
  todo_done: "完成待办",
  reminder_sent: "发送提醒",
  summary_generated: "生成总结",
};

const factTypeMap: Record<string, string> = {
  expense: "消费",
  mood: "状态",
  learning: "学习",
  plan: "计划",
};

const memoryStatusMap: Record<string, string> = {
  active: "已收好",
  archived: "已归档",
  deleted: "已删除",
};

const reviewStatusMap: Record<string, string> = {
  pending: "待处理",
  approved: "已授权",
  confirmed: "已确认",
  rejected: "已忽略",
};

const riskLevelMap: Record<string, string> = {
  low: "不用着急",
  medium: "留意一下",
  high: "尽快处理",
};

const notifyChannelMap: Record<string, string> = {
  wechat: "微信",
  email: "邮箱",
  app: "站内提醒",
  in_app: "站内提醒",
  pushdeer: "PushDeer",
  serverchan: "Server酱微信",
  wecom: "企业微信",
  sms: "短信",
};

const BEIJING_TIME_ZONE = "Asia/Shanghai";
const TIME_ZONE_PATTERN = /(z|[+-]\d{2}:?\d{2})$/i;

function parseApiDateTime(value: string) {
  const normalized = TIME_ZONE_PATTERN.test(value) ? value : `${value}Z`;
  return new Date(normalized);
}

export function formatCategory(category: string) {
  return categoryMap[category] ?? category;
}

export function formatTodoStatus(status: string) {
  return todoStatusMap[status] ?? status;
}

export function formatTodoPriority(priority: string) {
  return todoPriorityMap[priority] ?? priority;
}

export function formatReviewType(reviewType: string) {
  return reviewTypeMap[reviewType] ?? reviewType;
}

export function formatTimelineType(eventType: string) {
  return timelineTypeMap[eventType] ?? eventType;
}

export function formatFactType(factType: string) {
  return factTypeMap[factType] ?? factType;
}

export function formatMemoryStatus(status: string) {
  return memoryStatusMap[status] ?? status;
}

export function formatReviewStatus(status: string) {
  return reviewStatusMap[status] ?? status;
}

export function formatRiskLevel(level: string) {
  return riskLevelMap[level] ?? level;
}

export function formatNotifyChannel(channel: string) {
  return notifyChannelMap[channel] ?? channel;
}

export function formatDateTime(value: string | null) {
  if (!value) {
    return "没有具体时间";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDateTime(value));
}

export function formatDateTimeLong(value: string | null) {
  if (!value) {
    return "没有具体时间";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parseApiDateTime(value));
}

export function formatDateLabel(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(parseApiDateTime(value));
}

export function describeImportance(score: number) {
  if (score >= 0.8) {
    return "非常重要";
  }

  if (score >= 0.6) {
    return "值得留意";
  }

  if (score >= 0.4) {
    return "普通记录";
  }

  return "轻量记录";
}

export function formatCitationStrength(score: number) {
  if (score >= 0.85) {
    return "高度相关";
  }

  if (score >= 0.7) {
    return "比较相关";
  }

  if (score >= 0.5) {
    return "有一定关联";
  }

  return "弱关联";
}

export function formatQAModeLabel(mode: "memory_only" | "hybrid_web") {
  return mode === "memory_only" ? "只根据你的记录" : "记录 + 联网补充";
}

export function buildTitleFromText(text: string, fallback: string) {
  const compact = text.trim().replace(/\s+/g, " ");
  if (!compact) {
    return fallback;
  }

  return compact.length <= 18 ? compact : `${compact.slice(0, 18)}...`;
}
