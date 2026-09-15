import { useEffect, useMemo, useRef, useState } from "react";
import { AtSign, Command, CornerDownLeft } from "lucide-react";

function findTrigger(value, caret) {
  const beforeCaret = value.slice(0, caret);
  const match = beforeCaret.match(/(?:^|\s)([@/])([^\s]*)$/);
  if (!match) return null;
  return { type: match[1], query: match[2].toLowerCase(), start: caret - match[0].length + 1 };
}

export default function Compose({
  value,
  defaultValue = "",
  onChange,
  onSubmit,
  mentions = [],
  commands = [],
  placeholder = "Enter suspect wallet address (0x...) or TRON address (T...)",
  className = "",
}) {
  const [internalValue, setInternalValue] = useState(defaultValue);
  const [trigger, setTrigger] = useState(null);
  const textareaRef = useRef(null);
  const text = value ?? internalValue;

  const results = useMemo(() => {
    if (!trigger) return [];
    const source = trigger.type === "@" ? mentions : commands;
    return source.filter((item) => item.label.toLowerCase().includes(trigger.query)).slice(0, 5);
  }, [commands, mentions, trigger]);

  useEffect(() => {
    if (!trigger || results.length === 0) return;
    const onClick = () => setTrigger(null);
    window.addEventListener("click", onClick);
    return () => window.removeEventListener("click", onClick);
  }, [results.length, trigger]);

  function update(next) {
    if (value === undefined) setInternalValue(next);
    onChange?.(next);
  }

  function refreshTrigger() {
    const textarea = textareaRef.current;
    if (!textarea) return;
    setTrigger(findTrigger(textarea.value, textarea.selectionStart));
  }

  function insert(item) {
    const textarea = textareaRef.current;
    if (!textarea || !trigger) return;
    const caret = textarea.selectionStart;
    const token = `${trigger.type}${item.label}`;
    const next = text.slice(0, trigger.start) + token + " " + text.slice(caret);
    update(next);
    setTrigger(null);
    requestAnimationFrame(() => {
      textarea.focus();
      const position = trigger.start + token.length + 1;
      textarea.setSelectionRange(position, position);
    });
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      if (text.trim()) onSubmit?.(text.trim());
    }
    if (event.key === "Escape") setTrigger(null);
  }

  return (
    <div className={`relative ${className}`} onClick={(event) => event.stopPropagation()}>
      <div className="glass-input flex items-center gap-3 rounded-xl px-4 py-3">
        <AtSign className="h-4 w-4 shrink-0 text-slate-500" />
        <textarea
          ref={textareaRef}
          value={text}
          rows={1}
          placeholder={placeholder}
          aria-label="Suspect wallet address"
          onChange={(event) => update(event.target.value)}
          onKeyDown={handleKeyDown}
          onKeyUp={refreshTrigger}
          onClick={refreshTrigger}
          className="mono min-h-6 flex-1 resize-none bg-transparent text-sm text-slate-900 dark:text-slate-100 outline-none placeholder:text-slate-400 dark:placeholder:text-slate-600"
        />
        {text && <span className="text-xs text-slate-400 dark:text-slate-600">⌘↵</span>}
      </div>
      {trigger && results.length > 0 && (
        <div className="glass-panel absolute left-0 right-0 top-full z-30 mt-2 rounded-xl p-2 shadow-2xl">
          <div className="px-2 py-1 text-[10px] uppercase tracking-widest text-slate-500">
            {trigger.type === "@" ? "Mention source" : "Commands"}
          </div>
          {results.map((item) => (
            <button
              key={item.id ?? item.label}
              type="button"
              onClick={() => insert(item)}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-slate-300 transition hover:bg-white/10"
            >
              {trigger.type === "/" ? <Command size={14} /> : <AtSign size={14} />}
              <span className="flex-1">{item.label}</span>
              <span className="text-[10px] text-slate-600">{item.hint}</span>
            </button>
          ))}
          <div className="mt-1 flex items-center gap-1 px-2 pt-2 text-[10px] text-slate-600">
            <CornerDownLeft size={11} /> Select a suggestion
          </div>
        </div>
      )}
    </div>
  );
}
