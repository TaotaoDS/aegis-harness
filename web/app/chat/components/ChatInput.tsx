"use client";

import { useState, useRef, KeyboardEvent } from "react";

interface Props {
  onSend:      (text: string) => void;
  disabled?:   boolean;
  placeholder?: string;
}

export function ChatInput({ onSend, disabled = false, placeholder = "描述您想要构建的内容…" }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleInput = () => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  };

  return (
    <div className="flex items-end gap-3 bg-slate-800/60 border border-slate-700 rounded-2xl px-4 py-3">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKey}
        onInput={handleInput}
        disabled={disabled}
        placeholder={placeholder}
        rows={1}
        className="flex-1 bg-transparent text-slate-100 text-sm resize-none outline-none
                   placeholder-slate-500 leading-relaxed min-h-[24px] max-h-40"
      />
      <button
        onClick={submit}
        disabled={disabled || !value.trim()}
        className="shrink-0 w-9 h-9 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700
                   disabled:text-slate-500 text-white flex items-center justify-center transition-colors"
        title="发送 (Enter)"
      >
        <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 rotate-90">
          <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429
                   A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428
                   a1 1 0 001.17-1.408l-7-14z" />
        </svg>
      </button>
    </div>
  );
}
