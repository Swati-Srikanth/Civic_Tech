import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty" role="status">
      <h3>{title}</h3>
      {children ? <div className="muted">{children}</div> : null}
    </div>
  );
}
