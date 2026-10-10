import type { Priority } from "../types";
import { StatusBadge } from "./StatusBadge";

export function PriorityBadge({ priority, text }: { priority: Priority; text?: string }) {
  if (priority === "NORMAL") return null;
  return <StatusBadge tone={priority === "URGENT" ? "bad" : "warn"}>{text ?? (priority === "URGENT" ? "Urgent" : "High priority")}</StatusBadge>;
}
