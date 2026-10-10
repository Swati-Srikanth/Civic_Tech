import type { ReactNode } from "react";
import type { ApiRequestError } from "../api";
import { ErrorNotice, Notice } from "./Notice";

/** A titled box for one role's actions, with the server's success/error feedback. */
export function ActionPanel({
  title, description, children, error, success, onRefresh, fieldsShownInline,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  error?: ApiRequestError | null;
  success?: string | null;
  onRefresh?: () => void;
  fieldsShownInline?: boolean;
}) {
  return (
    <section className="card" aria-label={title}>
      <h3>{title}</h3>
      {description ? <p className="muted">{description}</p> : null}
      {children}
      <div aria-live="polite">
        {success ? <Notice kind="ok">{success}</Notice> : null}
        {error ? <ErrorNotice error={error} onRefresh={onRefresh} fieldsShownInline={fieldsShownInline} /> : null}
      </div>
    </section>
  );
}
