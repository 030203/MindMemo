import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Brain, CheckCircle2, UserRound } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { formatNotifyChannel } from "../utils/presentation";

const NOTIFY_CHANNELS = ["in_app", "pushdeer", "serverchan", "wecom"];

export function SettingsPage() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [lastTestResult, setLastTestResult] = useState<{ channel: string; ok: boolean } | null>(null);
  const [profileForm, setProfileForm] = useState({ display_name: "", email: "" });
  const [profileSaved, setProfileSaved] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
  });
  const { data: providerStatuses = [] } = useQuery({
    queryKey: ["notification-providers"],
    queryFn: api.getNotificationProviders,
  });

  useEffect(() => {
    if (data) {
      setSelectedChannels(data.notify_channels.includes("in_app") ? data.notify_channels : ["in_app", ...data.notify_channels]);
    }
  }, [data]);

  useEffect(() => {
    if (auth.user) {
      setProfileForm({
        display_name: auth.user.display_name,
        email: auth.user.email ?? "",
      });
    }
  }, [auth.user]);

  const updateProfile = useMutation({
    mutationFn: api.updateMe,
    onSuccess: (profile) => {
      auth.updateUser(profile);
      queryClient.setQueryData(["me"], profile);
      setProfileSaved(true);
    },
  });

  const updateSettings = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (updated) => {
      queryClient.setQueryData(["settings"], updated);
    },
  });

  const testNotification = useMutation({
    mutationFn: api.testNotification,
    onMutate: (channel) => {
      setLastTestResult({ channel, ok: false });
    },
    onSuccess: (result) => {
      setLastTestResult({ channel: result.channel, ok: true });
    },
  });

  if (isLoading) {
    return <div className="loading">正在加载配置...</div>;
  }

  if (error || !data) {
    return <div className="error">配置加载失败。</div>;
  }

  const normalizedSelectedChannels = selectedChannels.includes("in_app")
    ? selectedChannels
    : ["in_app", ...selectedChannels];
  const hasNotifyChanges = normalizedSelectedChannels.join("|") !== data.notify_channels.join("|");
  const profileHasChanges =
    Boolean(auth.user) &&
    (profileForm.display_name.trim() !== auth.user?.display_name || profileForm.email.trim() !== (auth.user?.email ?? ""));
  const providerStatusMap = new Map(providerStatuses.map((item) => [item.channel, item.configured]));
  const isConfigured = (channel: string) => channel === "in_app" || Boolean(providerStatusMap.get(channel));
  const channelStatusText = (channel: string) => {
    if (channel === "in_app") {
      return "始终可用";
    }
    if (!isConfigured(channel)) {
      return "未配置";
    }
    return normalizedSelectedChannels.includes(channel) ? "已开启" : "已配置";
  };
  const canTestChannel = (channel: string) =>
    channel !== "in_app" && normalizedSelectedChannels.includes(channel) && isConfigured(channel);

  const toggleChannel = (channel: string) => {
    setSelectedChannels((current) => {
      if (channel === "in_app") {
        return current.includes("in_app") ? current : ["in_app", ...current];
      }
      if (current.includes(channel)) {
        return current.filter((item) => item !== channel);
      }
      return [...current, channel];
    });
  };

  const handleProfileSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setProfileSaved(false);
    updateProfile.mutate({
      display_name: profileForm.display_name.trim(),
      email: profileForm.email.trim(),
    });
  };

  const profileError =
    updateProfile.error instanceof Error ? updateProfile.error.message : "保存失败，请检查输入后再试。";

  return (
    <div className="settings-page-shell">
      <section className="settings-hero">
        <div>
          <span>Settings</span>
          <h1>设置</h1>
          <p>只保留与你有关的轻量偏好：个人信息、后台通知，以及当前 AI 配置。</p>
        </div>
        <Link className="button-ghost settings-back-link" to="/">
          回到主页
        </Link>
      </section>

      <div className="settings-grid">
        <div className="settings-stack">
          <section className="settings-card">
            <header className="settings-card-header">
              <span className="settings-card-icon">
                <UserRound size={18} />
              </span>
              <div>
                <h2>个人信息</h2>
                <p>用于顶部显示和后续个性化记忆。</p>
              </div>
            </header>

            <form className="settings-form" onSubmit={handleProfileSubmit}>
              <label>
                <span>显示名称</span>
                <input
                  value={profileForm.display_name}
                  maxLength={64}
                  onChange={(event) => {
                    setProfileSaved(false);
                    setProfileForm((current) => ({ ...current, display_name: event.target.value }));
                  }}
                  placeholder="你的名字"
                  required
                />
              </label>
              <label>
                <span>邮箱</span>
                <input
                  type="email"
                  value={profileForm.email}
                  onChange={(event) => {
                    setProfileSaved(false);
                    setProfileForm((current) => ({ ...current, email: event.target.value }));
                  }}
                  placeholder="you@example.com"
                  required
                />
              </label>

              <div className="settings-action-row">
                <button
                  className="button primary"
                  type="submit"
                  disabled={!profileHasChanges || updateProfile.isPending}
                >
                  {updateProfile.isPending ? "保存中..." : "保存个人信息"}
                </button>
                {profileSaved ? (
                  <span className="success-text">
                    <CheckCircle2 size={15} /> 已更新
                  </span>
                ) : null}
                {updateProfile.isError ? <span className="error-text">{profileError}</span> : null}
              </div>
            </form>
          </section>

          <section className="settings-card">
            <header className="settings-card-header">
              <span className="settings-card-icon">
                <Bell size={18} />
              </span>
              <div>
                <h2>后台通知</h2>
                <p>决定提醒由哪些渠道发出，站内提醒会一直保留。</p>
              </div>
            </header>

            <div className="settings-meta-row">
              <span>当前时区</span>
              <strong>{data.timezone}</strong>
            </div>

            <div className="settings-channel-list">
              {NOTIFY_CHANNELS.map((channel) => (
                <div className="settings-channel-row" key={channel}>
                  <label className="settings-check">
                    <input
                      type="checkbox"
                      checked={normalizedSelectedChannels.includes(channel)}
                      disabled={channel === "in_app" || updateSettings.isPending}
                      onChange={() => toggleChannel(channel)}
                    />
                    <span>{formatNotifyChannel(channel)}</span>
                  </label>
                  <span className={`channel-status ${isConfigured(channel) ? "ready" : "missing"}`}>
                    {channelStatusText(channel)}
                  </span>
                  {channel === "in_app" ? null : (
                    <button
                      className="button-ghost"
                      type="button"
                      disabled={!canTestChannel(channel) || testNotification.isPending}
                      onClick={() => testNotification.mutate(channel)}
                    >
                      测试
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div className="settings-action-row">
              <button
                className="button primary"
                type="button"
                disabled={!hasNotifyChanges || updateSettings.isPending}
                onClick={() => updateSettings.mutate({ notify_channels: normalizedSelectedChannels })}
              >
                {updateSettings.isPending ? "保存中..." : "保存通知设置"}
              </button>
              {updateSettings.isError ? <span className="error-text">保存失败，请稍后再试。</span> : null}
              {updateSettings.isSuccess && !hasNotifyChanges ? <span className="success-text">通知设置已更新。</span> : null}
            </div>
            {testNotification.isError && lastTestResult ? (
              <span className="error-text">{formatNotifyChannel(lastTestResult.channel)} 测试发送失败，请检查渠道配置。</span>
            ) : null}
            {lastTestResult?.ok ? (
              <span className="success-text">{formatNotifyChannel(lastTestResult.channel)} 测试通知已发送。</span>
            ) : null}
          </section>
        </div>

        <aside className="settings-card ai-settings-card">
          <header className="settings-card-header">
            <span className="settings-card-icon">
              <Brain size={18} />
            </span>
            <div>
              <h2>AI 配置</h2>
              <p>这里展示当前问答和记忆理解使用的模型配置。</p>
            </div>
          </header>

          <div className="settings-info-list">
            <div className="settings-info-item">
              <span>模型服务</span>
              <strong>{data.llm_provider}</strong>
            </div>
            <div className="settings-info-item">
              <span>当前模型</span>
              <strong>{data.llm_model}</strong>
            </div>
            <div className="settings-info-item">
              <span>联网补充</span>
              <strong>{data.web_search_enabled ? "已开启" : "未开启"}</strong>
            </div>
          </div>

          <p className="settings-note">
            AI 问答仍会优先读取你的最近记录和相关记忆；联网补充只作为额外信息来源，不会替代本地记忆。
          </p>
        </aside>
      </div>
    </div>
  );
}
