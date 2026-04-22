"use client";

interface Task {
  id?: string;
  title?: string;
  description?: string;
  type?: string;
  status?: string;
}

interface Props {
  data: Record<string, unknown>;
}

/**
 * Renders the CEO development plan as a Kanban-style task board.
 *
 * Triggered by the `ceo.plan_created` event. The data field may contain:
 *   - tasks: Task[]   (detailed list)
 *   - task_count: number  (summary count only)
 */
export function TaskBoard({ data }: Props) {
  const tasks = (data.tasks ?? []) as Task[];
  const taskCount = (data.task_count as number) ?? tasks.length;

  if (tasks.length === 0) {
    return (
      <div className="bg-blue-900/20 border border-blue-700/40 rounded-xl px-4 py-3">
        <p className="text-blue-300 text-sm font-medium">
          📋 开发计划已生成，共 <strong>{taskCount}</strong> 个任务
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-blue-300 text-xs font-medium mb-2">
        📋 开发计划 — {taskCount} 个任务
      </p>
      <div className="grid grid-cols-1 gap-2">
        {tasks.map((task, idx) => (
          <div
            key={task.id ?? idx}
            className="bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2.5 flex items-start gap-3"
          >
            <span className="text-slate-500 font-mono text-xs mt-0.5 shrink-0">
              #{task.id ?? String(idx + 1).padStart(2, "0")}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-slate-200 text-sm font-medium truncate">
                {task.title ?? `任务 ${idx + 1}`}
              </p>
              {task.description && (
                <p className="text-slate-400 text-xs mt-0.5 line-clamp-2">
                  {task.description}
                </p>
              )}
            </div>
            {task.type && (
              <span className="text-xs text-slate-500 bg-slate-900 px-1.5 py-0.5 rounded shrink-0">
                {task.type}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
