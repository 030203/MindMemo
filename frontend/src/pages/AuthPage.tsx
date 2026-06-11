import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Clock3, KeyRound, NotebookPen, Search } from "lucide-react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { api } from "../api/client";

type AuthMode = "login" | "register";

const demoAccount = {
  account: "demo@example.com",
  password: "demo123456",
};

export function AuthPage() {
  const navigate = useNavigate();
  const auth = useAuth();
  const [mode, setMode] = useState<AuthMode>("login");
  const [loginForm, setLoginForm] = useState(demoAccount);
  const [registerForm, setRegisterForm] = useState({
    displayName: "",
    email: "",
    password: "",
    confirmPassword: "",
  });
  const [errorMessage, setErrorMessage] = useState("");

  const loginMutation = useMutation({
    mutationFn: api.login,
    onSuccess: (data) => {
      auth.applyAuthResponse(data);
      navigate("/app", { replace: true });
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "登录失败，请稍后再试。");
    },
  });

  const registerMutation = useMutation({
    mutationFn: api.register,
    onSuccess: (data) => {
      auth.applyAuthResponse(data);
      navigate("/app", { replace: true });
    },
    onError: (error) => {
      setErrorMessage(error instanceof Error ? error.message : "注册失败，请稍后再试。");
    },
  });

  if (auth.status === "loading") {
    return (
      <div className="auth-page auth-page-loading">
        <div className="auth-loading-card">
          <h3>正在准备你的空间</h3>
          <p className="panel-subtitle">如果你已经登录过，我会自动带你回去。</p>
        </div>
      </div>
    );
  }

  if (auth.isAuthenticated) {
    return <Navigate to="/app" replace />;
  }

  function handleLoginSubmit(event: FormEvent) {
    event.preventDefault();
    setErrorMessage("");

    if (!loginForm.account.trim() || !loginForm.password.trim()) {
      setErrorMessage("请先填写邮箱和密码。");
      return;
    }

    loginMutation.mutate({
      account: loginForm.account.trim(),
      password: loginForm.password,
    });
  }

  function handleRegisterSubmit(event: FormEvent) {
    event.preventDefault();
    setErrorMessage("");

    if (!registerForm.displayName.trim() || !registerForm.email.trim() || !registerForm.password.trim()) {
      setErrorMessage("请把昵称、邮箱和密码填写完整。");
      return;
    }

    if (registerForm.password.length < 6) {
      setErrorMessage("密码至少 6 位，会稳妥一些。");
      return;
    }

    if (registerForm.password !== registerForm.confirmPassword) {
      setErrorMessage("两次输入的密码不一致。");
      return;
    }

    registerMutation.mutate({
      display_name: registerForm.displayName.trim(),
      email: registerForm.email.trim(),
      password: registerForm.password,
    });
  }

  function fillDemoAccount() {
    setMode("login");
    setLoginForm(demoAccount);
    setErrorMessage("");
  }

  const isSubmitting = loginMutation.isPending || registerMutation.isPending;

  return (
    <div className="auth-page">
      <div className="auth-layout">
        <section className="auth-aside">
          <Link className="auth-home-link" to="/">
            <ArrowLeft size={16} />
            <span>返回首页</span>
          </Link>

          <div className="auth-brand">MindMemo</div>

          <div className="auth-copy">
            <span className="auth-kicker">长期记忆助手</span>
            <h1>{mode === "login" ? "继续把生活记下来。" : "给自己留一个长期的空间。"}</h1>
            <p>
              {mode === "login"
                ? "不用整理成系统，也不用每次都想清楚。想到什么，就先写下来。"
                : "像写备忘录一样开始就够了。之后的整理、回想和提醒，交给 MindMemo 慢慢帮你完成。"}
            </p>
          </div>

          <div className="auth-feature-stack">
            <div className="auth-feature-card">
              <span className="auth-feature-icon">
                <NotebookPen size={18} />
              </span>
              <div>
                <strong>先写一句也可以</strong>
                <span>不需要先想标题，也不需要先整理分类。</span>
              </div>
            </div>
            <div className="auth-feature-card">
              <span className="auth-feature-icon">
                <Search size={18} />
              </span>
              <div>
                <strong>想找的时候找得到</strong>
                <span>像和过去的自己聊天一样，把零散记录慢慢串起来。</span>
              </div>
            </div>
            <div className="auth-feature-card">
              <span className="auth-feature-icon">
                <Clock3 size={18} />
              </span>
              <div>
                <strong>留给未来的自己</strong>
                <span>把小事、念头和经历沉淀下来，时间久了就会很有价值。</span>
              </div>
            </div>
          </div>
        </section>

        <section className="auth-card" aria-label={mode === "login" ? "登录表单" : "注册表单"}>
          <div className="auth-card-header">
            <div>
              <h2>{mode === "login" ? "登录你的空间" : "创建一个新空间"}</h2>
              <p>{mode === "login" ? "继续记录你的生活、安排和想法。" : "注册后会自动进入你的专属记忆空间。"}</p>
            </div>
            <div className="auth-privacy-note">
              <KeyRound size={16} />
              <span>你的记录只属于你</span>
            </div>
          </div>

          <div className="auth-switch" role="tablist" aria-label="登录或注册">
            <button
              className={`auth-switch-button${mode === "login" ? " active" : ""}`}
              type="button"
              onClick={() => {
                setMode("login");
                setErrorMessage("");
              }}
            >
              登录
            </button>
            <button
              className={`auth-switch-button${mode === "register" ? " active" : ""}`}
              type="button"
              onClick={() => {
                setMode("register");
                setErrorMessage("");
              }}
            >
              注册
            </button>
          </div>

          {mode === "login" ? (
            <form className="auth-form" onSubmit={handleLoginSubmit}>
              <label className="auth-field">
                <span>邮箱 / 手机号 / 用户名</span>
                <input
                  className="auth-input"
                  placeholder="输入你的账号"
                  value={loginForm.account}
                  onChange={(event) => setLoginForm((prev) => ({ ...prev, account: event.target.value }))}
                />
              </label>
              <label className="auth-field">
                <span>密码</span>
                <input
                  className="auth-input"
                  type="password"
                  placeholder="输入密码"
                  value={loginForm.password}
                  onChange={(event) => setLoginForm((prev) => ({ ...prev, password: event.target.value }))}
                />
              </label>
              {errorMessage ? <div className="auth-inline-error">{errorMessage}</div> : null}
              <div className="auth-form-actions">
                <button className="auth-submit-button" type="submit" disabled={isSubmitting}>
                  {loginMutation.isPending ? "正在登录..." : "登录并继续"}
                </button>
                <button
                  className="auth-secondary-button"
                  type="button"
                  disabled={isSubmitting}
                  onClick={() => {
                    setErrorMessage("");
                    loginMutation.mutate(demoAccount);
                  }}
                >
                  一键进入演示空间
                </button>
              </div>
            </form>
          ) : (
            <form className="auth-form" onSubmit={handleRegisterSubmit}>
              <label className="auth-field">
                <span>昵称</span>
                <input
                  className="auth-input"
                  placeholder="怎么称呼你？"
                  value={registerForm.displayName}
                  onChange={(event) => setRegisterForm((prev) => ({ ...prev, displayName: event.target.value }))}
                />
              </label>
              <label className="auth-field">
                <span>邮箱</span>
                <input
                  className="auth-input"
                  placeholder="name@example.com"
                  value={registerForm.email}
                  onChange={(event) => setRegisterForm((prev) => ({ ...prev, email: event.target.value }))}
                />
              </label>
              <label className="auth-field">
                <span>密码</span>
                <input
                  className="auth-input"
                  type="password"
                  placeholder="至少 6 位"
                  value={registerForm.password}
                  onChange={(event) => setRegisterForm((prev) => ({ ...prev, password: event.target.value }))}
                />
              </label>
              <label className="auth-field">
                <span>确认密码</span>
                <input
                  className="auth-input"
                  type="password"
                  placeholder="再输入一次密码"
                  value={registerForm.confirmPassword}
                  onChange={(event) => setRegisterForm((prev) => ({ ...prev, confirmPassword: event.target.value }))}
                />
              </label>
              {errorMessage ? <div className="auth-inline-error">{errorMessage}</div> : null}
              <div className="auth-form-actions">
                <button className="auth-submit-button" type="submit" disabled={isSubmitting}>
                  {registerMutation.isPending ? "正在创建..." : "注册并进入"}
                </button>
              </div>
            </form>
          )}

          <div className="auth-demo-box">
            <div className="auth-demo-copy">
              <span className="auth-demo-label">演示账号</span>
              <strong>{demoAccount.account}</strong>
              <span>{demoAccount.password}</span>
            </div>
            <button
              className="auth-demo-link"
              type="button"
              onClick={() => {
                fillDemoAccount();
                navigate("/auth", { replace: true });
              }}
            >
              先帮我填好
              <ArrowRight size={16} />
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
