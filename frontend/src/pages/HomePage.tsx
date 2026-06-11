import {
  ArrowRight,
  BookOpenText,
  LockKeyhole,
  MessageCircleMore,
  Milestone,
  Sparkles,
} from "lucide-react";
import { Navigate, Link } from "react-router-dom";
import illustration from "../assets/mindmemo-home-illustration.png";
import { useAuth } from "../auth/AuthProvider";

const featureCards = [
  {
    icon: Sparkles,
    title: "先写一句也可以",
    description: "不需要先想标题，更不需要先整理分类。",
  },
  {
    icon: LockKeyhole,
    title: "你的记录只属于你",
    description: "登录后会进入自己的独立空间。",
  },
  {
    icon: MessageCircleMore,
    title: "想找的时候找得到",
    description: "像和过去的自己聊天一样。",
  },
  {
    icon: Milestone,
    title: "AI帮你整理成长轨迹",
    description: "长期沉淀你的经历和思考。",
  },
];

export function HomePage() {
  const auth = useAuth();

  if (auth.status === "authenticated") {
    return <Navigate to="/app" replace />;
  }

  return (
    <div className="marketing-shell">
      <header className="marketing-nav">
        <Link className="marketing-brand" to="/">
          <span className="marketing-brand-mark">
            <BookOpenText size={18} />
          </span>
          <span>MindMemo</span>
        </Link>

        <nav className="marketing-nav-links" aria-label="主导航">
          <a href="#features">为什么好用</a>
          <a href="#memory-flow">怎么记录</a>
          <a href="#trust">为什么安心</a>
        </nav>

        <div className="marketing-nav-actions">
          <Link className="marketing-link" to="/auth">
            登录
          </Link>
          <Link className="marketing-nav-cta" to="/auth">
            开始记录
          </Link>
        </div>
      </header>

      <main className="marketing-main">
        <section className="marketing-hero">
          <div className="marketing-hero-copy">
            <span className="marketing-kicker">长期记忆助手</span>
            <h1>
              把琐碎的小事先记下来，
              <br />
              脑子会轻松很多。
            </h1>
            <p>
              这是一个为普通人准备的长期记忆助手。
              <br />
              你只需要像写备忘录一样输入，
              <br />
              我会帮你收纳、回想和提醒。
            </p>

            <div className="marketing-hero-actions">
              <Link className="marketing-primary-button" to="/auth">
                开始记录
              </Link>
              <Link className="marketing-secondary-button" to="/auth">
                体验演示
              </Link>
            </div>
          </div>

          <div className="marketing-hero-visual" aria-hidden="true">
            <img src={illustration} alt="" />
          </div>
        </section>

        <section className="marketing-feature-band" id="features">
          {featureCards.map((feature) => {
            const Icon = feature.icon;
            return (
              <article className="marketing-feature-card" key={feature.title}>
                <span className="marketing-feature-icon">
                  <Icon size={18} />
                </span>
                <h2>{feature.title}</h2>
                <p>{feature.description}</p>
              </article>
            );
          })}
        </section>

        <section className="marketing-story-grid" id="memory-flow">
          <div className="marketing-story-panel">
            <span className="marketing-section-label">记录方式</span>
            <h3>像写备忘录一样自然。</h3>
            <p>
              记一条念头、一个待办、一段反思，或者一张截图。
              不需要先决定放在哪一类，也不用先把语言整理漂亮。
            </p>
          </div>

          <div className="marketing-story-panel" id="trust">
            <span className="marketing-section-label">陪伴感</span>
            <h3>不是更吵的工具，是更安静的长期空间。</h3>
            <p>
              它不会催促你经营系统，也不会逼你变成效率机器。
              只是把每天容易散掉的东西，慢慢存成能回头看的自己。
            </p>
          </div>
        </section>

        <section className="marketing-cta-band">
          <div>
            <span className="marketing-section-label">准备开始</span>
            <h3>先写第一句，剩下的再慢慢长出来。</h3>
          </div>
          <Link className="marketing-inline-cta" to="/auth">
            去登录或注册
            <ArrowRight size={18} />
          </Link>
        </section>
      </main>
    </div>
  );
}
