import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckCircle2, Clock, UserRound } from "lucide-react";
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
    return (
      <div className="st-page">
        <div className="st-loading">
          <div className="st-loading-spinner" />
          <span>正在加载配置...</span>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="st-page">
        <div className="st-error">配置加载失败，请刷新重试。</div>
      </div>
    );
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
    if (channel === "in_app") return "始终可用";
    if (!isConfigured(channel)) return "未配置";
    return normalizedSelectedChannels.includes(channel) ? "已开启" : "已配置";
  };
  const channelStatusClass = (channel: string) => {
    if (channel === "in_app") return "always";
    return isConfigured(channel) ? "ready" : "missing";
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
    <div className="st-page">
      <div className="st-header">
        <UserRound size={28} className="st-header-icon" />
        <div>
          <h1 className="st-title">设置</h1>
          <p className="st-subtitle">管理你的个人信息和通知偏好，让 MindMemo 更贴合你的使用习惯。</p>
        </div>
      </div>

      <div className="st-stack">
        {/* ── 个人信息卡片 ── */}
        <section className="st-card">
          <header className="st-card-header">
            <span className="st-card-icon profile-icon">
              <UserRound size={18} />
            </span>
            <div className="st-card-heading">
              <h2>个人信息</h2>
              <p>用于顶部显示和后续个性化记忆。</p>
            </div>
          </header>

          <form className="st-form" onSubmit={handleProfileSubmit}>
            <div className="st-field">
              <label className="st-field-label">显示名称</label>
              <input
                className="st-input"
                value={profileForm.display_name}
                maxLength={64}
                onChange={(event) => {
                  setProfileSaved(false);
                  setProfileForm((current) => ({ ...current, display_name: event.target.value }));
                }}
                placeholder="你的名字"
                required
              />
            </div>
            <div className="st-field">
              <label className="st-field-label">邮箱</label>
              <input
                className="st-input"
                type="email"
                value={profileForm.email}
                onChange={(event) => {
                  setProfileSaved(false);
                  setProfileForm((current) => ({ ...current, email: event.target.value }));
                }}
                placeholder="you@example.com"
                required
              />
            </div>

            <div className="st-action-row">
              <button
                className="st-save-btn"
                type="submit"
                disabled={!profileHasChanges || updateProfile.isPending}
              >
                {updateProfile.isPending ? "保存中..." : "保存个人信息"}
              </button>
              {profileSaved ? (
                <span className="st-feedback success">
                  <CheckCircle2 size={15} /> 已更新
                </span>
              ) : null}
              {updateProfile.isError ? (
                <span className="st-feedback error">{profileError}</span>
              ) : null}
            </div>
          </form>
        </section>

        {/* ── 后台通知卡片 ── */}
        <section className="st-card">
          <header className="st-card-header">
            <span className="st-card-icon notify-icon">
              <Bell size={18} />
            </span>
            <div className="st-card-heading">
              <h2>后台通知</h2>
              <p>决定提醒由哪些渠道发出，站内通知会一直保留。</p>
            </div>
          </header>

          <div className="st-meta-strip">
            <Clock size={14} />
            <span>当前时区</span>
            <strong>{data.timezone}</strong>
          </div>

          <div className="st-channel-list">
            {NOTIFY_CHANNELS.map((channel) => {
              const checked = normalizedSelectedChannels.includes(channel);
              const isActive = checked && isConfigured(channel);
              return (
                <div className={`st-channel-row${isActive ? " active" : ""}`} key={channel}>
                  <label className="st-toggle">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={channel === "in_app" || updateSettings.isPending}
                      onChange={() => toggleChannel(channel)}
                    />
                    <span className="st-toggle-track">
                      <span className="st-toggle-thumb" />
                    </span>
                    <span className="st-toggle-label">{formatNotifyChannel(channel)}</span>
                  </label>
                  <span className={`st-channel-status ${channelStatusClass(channel)}`}>
                    {channelStatusText(channel)}
                  </span>
                  {channel !== "in_app" && (
                    <button
                      className="st-test-btn"
                      type="button"
                      disabled={!canTestChannel(channel) || testNotification.isPending}
                      onClick={() => testNotification.mutate(channel)}
                    >
                      测试
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          <div className="st-action-row">
            <button
              className="st-save-btn"
              type="button"
              disabled={!hasNotifyChanges || updateSettings.isPending}
              onClick={() => updateSettings.mutate({ notify_channels: normalizedSelectedChannels })}
            >
              {updateSettings.isPending ? "保存中..." : "保存通知设置"}
            </button>
            {updateSettings.isError ? (
              <span className="st-feedback error">保存失败，请稍后再试。</span>
            ) : null}
            {updateSettings.isSuccess && !hasNotifyChanges ? (
              <span className="st-feedback success">
                <CheckCircle2 size={15} /> 通知设置已更新
              </span>
            ) : null}
          </div>
          {testNotification.isError && lastTestResult ? (
            <span className="st-feedback error" style={{ marginTop: 8 }}>
              {formatNotifyChannel(lastTestResult.channel)} 测试发送失败，请检查渠道配置。
            </span>
          ) : null}
          {lastTestResult?.ok ? (
            <span className="st-feedback success" style={{ marginTop: 8 }}>
              <CheckCircle2 size={15} />
              {formatNotifyChannel(lastTestResult.channel)} 测试通知已发送
            </span>
          ) : null}
        </section>
      </div>
    </div>
  );
}
