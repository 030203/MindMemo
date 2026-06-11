interface StatCardProps {
  label: string;
  value: string | number;
  detail: string;
}

export function StatCard({ label, value, detail }: StatCardProps) {
  return (
    <section className="panel stat-card">
      <div className="stat-topline">
        <div className="stat-label">{label}</div>
        <span className="stat-indicator" />
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-detail">{detail}</div>
    </section>
  );
}
