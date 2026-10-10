import { useId, type ReactNode } from "react";

/** Visible label, brief help, and the server's error message right beside the control. */
export function Field({
  label, help, error, children, className = "",
}: {
  label: string;
  help?: string;
  error?: string;
  className?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}) {
  const id = useId();
  const describedBy = [help ? `${id}-help` : "", error ? `${id}-err` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className={`field ${error ? "field--invalid" : ""} ${className}`}>
      <label className="field__label" htmlFor={id}>{label}</label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {help ? <div className="field__help" id={`${id}-help`}>{help}</div> : null}
      {error ? <div className="field__error" id={`${id}-err`}>{error}</div> : null}
    </div>
  );
}
