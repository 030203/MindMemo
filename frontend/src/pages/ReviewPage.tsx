import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatReviewStatus, formatReviewType } from "../utils/presentation";

export function ReviewPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["reviews"],
    queryFn: api.listReviews,
  });

  const refreshAfterDecision = () => {
    queryClient.invalidateQueries({ queryKey: ["reviews"] });
    queryClient.invalidateQueries({ queryKey: ["todos"] });
    queryClient.invalidateQueries({ queryKey: ["timeline"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
  };

  const confirmReview = useMutation({
    mutationFn: api.confirmReview,
    onSuccess: refreshAfterDecision,
  });
  const ignoreReview = useMutation({
    mutationFn: api.ignoreReview,
    onSuccess: refreshAfterDecision,
  });
  const convertReviewToTodo = useMutation({
    mutationFn: api.convertReviewToTodo,
    onSuccess: refreshAfterDecision,
  });

  const isActing = confirmReview.isPending || ignoreReview.isPending || convertReviewToTodo.isPending;

  if (isLoading) {
    return <div className="loading">正在加载待确认项...</div>;
  }

  if (error || !data) {
    return <div className="error">待确认列表加载失败。</div>;
  }

  return (
    <div className="page-grid">
      <section className="panel warm-panel">
        <h3>这些内容想请你看一眼</h3>
        <p className="panel-subtitle">当信息冲突、置信度不足，或者需要你授权时，我会先放到这里，不会擅自改动。</p>
      </section>

      <section className="panel">
        <div className="section-title">
          <h3>待确认列表</h3>
          <span className="muted">{data.length} 条</span>
        </div>

        <div className="list">
          {data.length === 0 ? (
            <div className="empty-state">目前没有需要你确认的内容，一切都很清爽。</div>
          ) : (
            data.map((item) => (
              <div className="list-item" key={item.id}>
                <div className="list-item-header">
                  <strong>{item.target_title}</strong>
                  <span className="soft-tag">{formatReviewType(item.review_type)}</span>
                </div>
                <p className="panel-subtitle">{item.reason}</p>
                <div className="inline-meta">
                  <span>{formatReviewStatus(item.status)}</span>
                </div>
                {item.status === "pending" ? (
                  <div className="review-actions">
                    <button className="button" type="button" disabled={isActing} onClick={() => confirmReview.mutate(item.id)}>
                      确认
                    </button>
                    <button className="button-ghost" type="button" disabled={isActing} onClick={() => convertReviewToTodo.mutate(item.id)}>
                      转成 TODO
                    </button>
                    <button className="button-ghost" type="button" disabled={isActing} onClick={() => ignoreReview.mutate(item.id)}>
                      忽略
                    </button>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
