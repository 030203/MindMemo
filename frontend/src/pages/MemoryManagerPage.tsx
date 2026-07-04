import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Brain, Clock3, History, Loader2, Play, Repeat, ShieldAlert, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { MaintenanceReport } from "../api/types";
import { StatCard } from "../components/ui/StatCard";

function formatMemoryStatLabel(key: string) {
  const map: Record<string, string> = {
    duplicates_found: "发现疑似重复",
    decayed_memories: "已衰减记忆",
    expired_insights: "清理过期洞察",
    users_processed: "处理用户数",
  };
  return map[key] ?? key;
}

function describeStatSignificance(key: string, value: number) {
  if (key === "duplicates_found") {
    return value === 0 ? "记忆库很干净，没有检测到疑似重复的记录。" : "建议去 Review Queue 确认这些重复项。";
  }
  if (key === "decayed_memories") {
    return value === 0 ? "没有长期未访问的记忆需要衰减。" : "这些记忆已经很久没有回顾了，重要性已自动降低。";
  }
  if (key === "expired_insights") {
    return value === 0 ? "洞察缓存全部有效。" : "已清理过期洞察，释放缓存空间。";
  }
  return "";
}

function formatMaintenanceTime(iso: string | null | undefined) {
  if (!iso) return "从未执行";
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "从未执行";
  }
}

export function MemoryManagerPage() {
  const queryClient = useQueryClient();
  const [lastReport, setLastReport] = useState<MaintenanceReport | null>(null);

  const { data: dashboard } = useQuery({
    queryKey: ["dashboard-overview"],
    queryFn: api.getDashboardOverview,
  });

  const { data: memories } = useQuery({
    queryKey: ["memories", "all"],
    queryFn: () => api.listMemories(),
  });

  const { data: adminMe } = useQuery({
    queryKey: ["admin-me"],
    queryFn: api.getAdminMe,
  });

  const maintenanceMutation = useMutation({
    mutationFn: api.runMaintenance,
    onSuccess: (report) => {
      setLastReport(report);
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.invalidateQueries({ queryKey: ["insights"] });
      queryClient.invalidateQueries({ queryKey: ["admin-me"] });
    },
  });

  const memoryCount = memories?.length ?? 0;
  const activeMemories = memories?.filter((m) => m.status === "active").length ?? 0;
  const pendingReviews = dashboard?.pending_reviews ?? 0;

  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="eyebrow">Memory Manager</span>
          <h3>记忆库健康维护</h3>
          <p>
            Memory Manager 是你的记忆库管家，定期自动或手动触发去重检测、重要性衰减和过期数据清理。
          </p>
        </div>
        <div className="maintenance-hero-actions">
          <button
            className="button"
            type="button"
            disabled={maintenanceMutation.isPending}
            onClick={() => maintenanceMutation.mutate()}
          >
            {maintenanceMutation.isPending ? (
              <>
                <Loader2 className="spin" size={16} />
                正在执行维护...
              </>
            ) : (
              <>
                <Play size={16} />
                立即执行维护
              </>
            )}
          </button>
        </div>
      </section>

      <section className="kpi-grid">
        <StatCard label="记忆总数" value={memoryCount} detail="你的第二大脑当前存储的所有记忆" />
        <StatCard label="活跃记录" value={activeMemories} detail="仍在活跃使用中的记忆" />
        <StatCard label="待确认项" value={pendingReviews} detail="需要你去 Review Queue 确认的内容" />
        <div className="stat-card panel">
          <div className="stat-topline">
            <span className="stat-label">上次维护</span>
            <History size={16} className="muted" />
          </div>
          <div className="stat-value" style={{ fontSize: "1rem" }}>
            {formatMaintenanceTime(adminMe?.last_maintenance_at)}
          </div>
          <div className="stat-detail">
            最近一次运行维护的时间
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-title">
          <h3>维护机制说明</h3>
          <Repeat size={18} className="muted" />
        </div>
        <p className="panel-subtitle">
          Memory Manager 由三个核心机制组成，每次维护按顺序执行。你可以手动触发。
        </p>
        <div className="maintenance-mechanism-grid">
          <div className="maintenance-mechanism-card">
            <div className="mechanism-icon">
              <ShieldAlert size={22} />
            </div>
            <div>
              <strong>去重检测</strong>
              <p>
                扫描最近 30 天记忆，通过标题相似度找出疑似重复项。不会自动合并，会放入 Review Queue 等你确认。
              </p>
              <span className="soft-tag">Jaccard 相似度 &gt; 70%</span>
            </div>
          </div>
          <div className="maintenance-mechanism-card">
            <div className="mechanism-icon">
              <Clock3 size={22} />
            </div>
            <div>
              <strong>重要性衰减</strong>
              <p>
                长期未被回顾的记忆，系统会认为它们不再重要，自动降低其重要性分数。
              </p>
              <div className="decay-rule-strip">
                <span className="soft-tag">&gt; 90 天未访问 → 权重 × 0.5</span>
                <span className="soft-tag">&gt; 180 天未访问 → 权重 × 0.3</span>
              </div>
            </div>
          </div>
          <div className="maintenance-mechanism-card">
            <div className="mechanism-icon">
              <Trash2 size={22} />
            </div>
            <div>
              <strong>过期清理</strong>
              <p>
                清理已过期的 AI 洞察缓存，释放空间。新洞察会根据最新记忆重新生成。
              </p>
            </div>
          </div>
        </div>
      </section>

      {lastReport ? (
        <section className="panel">
          <div className="section-title">
            <h3>本次维护结果</h3>
            <Archive size={18} className="muted" />
          </div>
          <div className="maintenance-report-grid">
            {Object.entries(lastReport).map(([key, value]) => (
              <div className="maintenance-stat-card" key={key}>
                <strong>{value as number}</strong>
                <span>{formatMemoryStatLabel(key)}</span>
                <p className="muted">{describeStatSignificance(key, value as number)}</p>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="panel">
          <div className="section-title">
            <h3>维护结果</h3>
            <Archive size={18} className="muted" />
          </div>
          <div className="empty-state">
            <Brain size={20} />
            <p>还没有执行过维护。点击上方按钮触发一次。</p>
          </div>
        </section>
      )}

      {maintenanceMutation.isError ? (
        <div className="error">维护执行失败：{(maintenanceMutation.error as Error).message}</div>
      ) : null}
    </div>
  );
}
