import { LogOut, MessageCircle, Search, Settings, Sparkles, UserRound } from "lucide-react";
import { Link, Outlet } from "react-router-dom";
import { useAuth } from "../../auth/AuthProvider";

function openAiDrawer() {
  window.dispatchEvent(new Event("open-ai-drawer"));
}

export function AppShell() {
  const auth = useAuth();

  return (
    <div className="minimal-shell">
      <header className="minimal-topbar">
        <Link className="minimal-brand" to="/app">
          <span className="minimal-brand-mark">
            <Sparkles size={18} />
          </span>
          <span>MindMemo</span>
        </Link>

        <div className="minimal-search" aria-label="搜索记录">
          <Search size={16} />
          <input placeholder="搜索最近记录..." />
        </div>

        <div className="minimal-actions">
          <button className="icon-text-button" type="button" onClick={openAiDrawer}>
            <MessageCircle size={17} />
            AI
          </button>
          <Link className="icon-button" to="/app/settings" aria-label="打开设置" title="设置">
            <Settings size={17} />
          </Link>
          <div className="minimal-user">
            <UserRound size={16} />
            <span>{auth.user?.display_name ?? "我"}</span>
          </div>
          <button className="icon-button" type="button" onClick={auth.logout} aria-label="退出登录">
            <LogOut size={17} />
          </button>
        </div>
      </header>

      <main className="minimal-page">
        <Outlet />
      </main>
    </div>
  );
}
