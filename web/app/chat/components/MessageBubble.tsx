"use client";

// ---------------------------------------------------------------------------
// MessageBubble — renders a single chat message
// ---------------------------------------------------------------------------

export type MessageRole = "user" | "bot" | "system";

export interface ChatMessage {
  id:       string;
  role:     MessageRole;
  content:  string;
  options?: string[];   // clickable option buttons (non-tech CEO interview)
  ts?:      number;
}

interface Props {
  message:        ChatMessage;
  onOptionClick?: (option: string) => void;
}

export function MessageBubble({ message, onOptionClick }: Props) {
  const { role, content, options } = message;

  if (role === "system") {
    return (
      <div className="flex justify-center my-2">
        <span className="text-xs text-slate-500 bg-slate-800/60 px-3 py-1 rounded-full">
          {content}
        </span>
      </div>
    );
  }

  const isUser = role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div className={`max-w-[75%] ${isUser ? "" : "flex flex-col gap-2"}`}>
        {/* Avatar + bubble */}
        <div className={`flex items-end gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
          {/* Avatar */}
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center text-sm shrink-0 ${
              isUser ? "bg-blue-600" : "bg-violet-700"
            }`}
          >
            {isUser ? "👤" : "🤖"}
          </div>

          {/* Text bubble */}
          <div
            className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
              isUser
                ? "bg-blue-600 text-white rounded-br-sm"
                : "bg-slate-700 text-slate-100 rounded-bl-sm"
            }`}
          >
            {content}
          </div>
        </div>

        {/* Options buttons (non-technical interview mode) */}
        {!isUser && options && options.length > 0 && (
          <div className="flex flex-col gap-1.5 ml-10">
            {options.map((opt, idx) => (
              <button
                key={idx}
                onClick={() => onOptionClick?.(opt)}
                className="text-left text-sm px-4 py-2 rounded-xl border border-violet-500/40
                           bg-violet-900/20 text-violet-200 hover:bg-violet-600/30
                           hover:border-violet-400 transition-colors"
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
