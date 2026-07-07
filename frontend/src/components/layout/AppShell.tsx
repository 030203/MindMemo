import {
  BellRing,
  BookOpenText,
  Brain,
  CheckSquare,
  ChevronRight,
  Inbox,
  LayoutDashboard,
  MessageSquare,
  Search,
  Moon,
  Settings,
  Sparkles,
  Sun,
} from "lucide-react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useTheme } from "../../utils/useTheme";
import { useState } from "react";
import { useAuth } from "../../auth/AuthProvider";

const navItems = [
  { to: "/app", icon: LayoutDashboard, label: "工作台", end: true },
  { to: "/app/inbox", icon: Inbox, label: "收件箱" },
  { to: "/app/memories", icon: Brain, label: "我的记录" },
  { to: "/app/todos", icon: CheckSquare, label: "待办" },
  { to: "/app/reminders", icon: BellRing, label: "提醒" },
];

export function AppShell() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [searchQuery, setSearchQuery] = useState("");

  const displayName = auth.user?.display_name ?? "我";
  const initial = displayName.trim().charAt(0).toUpperCase() || "M";

  function handleSearchSubmit(event: React.FormEvent) {
    event.preventDefault();
    const q = searchQuery.trim();
    if (!q) return;
    navigate(`/app/memories?q=${encodeURIComponent(q)}`);
    setSearchQuery("");
  }

  return (
    <div className="studio-layout">
      <aside className="studio-sidebar">
        <Link className="studio-brand" to="/app">
          <span className="studio-brand-mark">
            <BookOpenText size={18} />
          </span>
          <span className="studio-brand-copy">
            <strong>MindMemo</strong>
          </span>
        </Link>

        <nav className="studio-nav" aria-label="主导航">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `studio-nav-item${isActive ? " active" : ""}`}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
            </NavLink>
          ))}

          <span className="studio-nav-divider" />

          <NavLink
            to="/app/chat"
            className={({ isActive }) => `studio-nav-item${isActive ? " active" : ""}`}
          >
            <Sparkles size={18} />
            <span>AI 对话</span>
          </NavLink>

          <button
            type="button"
            className="studio-nav-item studio-theme-toggle"
            onClick={toggleTheme}
            title={theme === "dark" ? "\u5207\u6362\u4eae\u8272\u6a21\u5f0f" : "\u5207\u6362\u6697\u8272\u6a21\u5f0f"}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            <span>{theme === "dark" ? "\u4eae\u8272\u6a21\u5f0f" : "\u6697\u8272\u6a21\u5f0f"}</span>
          </button>

          <span className="studio-nav-divider" />

          <NavLink
            to="/app/settings"
            className={({ isActive }) => `studio-nav-item${isActive ? " active" : ""}`}
          >
            <Settings size={18} />
            <span>设置</span>
          </NavLink>
        </nav>

        <div className="studio-sidebar-footer">
          <div className="studio-user-card">
            <span className="studio-user-avatar">{initial}</span>
            <div className="studio-user-copy">
              <strong>{displayName}</strong>
              <span>{auth.user?.email ?? "个人空间"}</span>
            </div>
            <button
              className="studio-user-action"
              type="button"
              onClick={auth.logout}
              aria-label="退出登录"
              title="退出登录"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      </aside>

      <div className="studio-main">
        <header className="studio-topbar">
          <form className="studio-search" onSubmit={handleSearchSubmit}>
            <Search size={16} />
            <input
              placeholder="搜索想法、待办、文件..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </form>
          <div className="studio-topbar-actions">
            <Link
              className="studio-action-button"
              to="/app/chat"
            >
              <MessageSquare size={15} />
              AI 对话
            </Link>
          </div>
        </header>

        <main className="studio-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
