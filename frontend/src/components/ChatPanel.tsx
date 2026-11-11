import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Bot, MessageSquare, Send, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '@/lib/api';
import { useToast } from '@/lib/toast';

interface Msg {
  id?: number;
  role: 'user' | 'assistant';
  content: string;
  tool_calls?: { name: string }[] | null;
}

const EXAMPLES = ['chat.ex1', 'chat.ex2', 'chat.ex3', 'chat.ex4', 'chat.ex5'];

export function ChatButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation();
  return (
    <button className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800" onClick={onClick}
      aria-label={t('common.openAssistant')} title={t('common.openAssistant')}>
      <MessageSquare className="h-5 w-5" />
    </button>
  );
}

/** Slide-over assistant available on every page (spec 9.18). */
export function ChatPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const [pending, setPending] = useState<Msg[]>([]);
  const end = useRef<HTMLDivElement>(null);
  const history = useQuery({ queryKey: ['chat'], queryFn: () => api.get<Msg[]>('/assistant/history'), enabled: open });
  const status = useQuery({ queryKey: ['assistant-status'], queryFn: () => api.get<{ llm: { provider: string; configured: boolean } }>('/assistant/status'), enabled: open, staleTime: 300_000 });
  const send = useMutation({
    mutationFn: (message: string) => api.post<{ reply: string; mode: string }>('/assistant/chat', { message }),
    onMutate: (message) => setPending([{ role: 'user', content: message }]),
    onSettled: () => { setPending([]); void qc.invalidateQueries({ queryKey: ['chat'] }); void qc.invalidateQueries({ queryKey: ['prs'] }); },
    onError: (e) => toast.error(e),
  });
  const clear = useMutation({ mutationFn: () => api.del('/assistant/history'), onSuccess: () => void qc.invalidateQueries({ queryKey: ['chat'] }) });
  const msgs = [...(history.data ?? []), ...pending];
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth' });
  }, [msgs.length, open]);
  const submit = (m: string) => {
    if (!m.trim() || send.isPending) return;
    send.mutate(m.trim());
    setText('');
  };
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30" onMouseDown={onClose}>
      <aside className="flex h-full w-full max-w-md flex-col bg-white shadow-2xl dark:bg-slate-900" onMouseDown={(e) => e.stopPropagation()}
        role="dialog" aria-label={t('chat.title')}>
        <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <Bot className="h-5 w-5 text-violet-600" />
          <div className="flex-1">
            <p className="text-sm font-semibold">{t('chat.title')}</p>
            <p className="text-[11px] text-slate-500">
              {status.data?.llm.configured ? t('chat.modeLlm', { provider: status.data.llm.provider }) : t('chat.modeRules')}
            </p>
          </div>
          <button className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => clear.mutate()} aria-label={t('chat.clear')} title={t('chat.clear')}>
            <Trash2 className="h-4 w-4" />
          </button>
          <button className="rounded p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={onClose} aria-label={t('common.close')}>
            <X className="h-5 w-5" />
          </button>
        </header>
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {msgs.length === 0 && (
            <div className="space-y-2">
              <p className="text-sm text-slate-500">{t('chat.intro')}</p>
              {EXAMPLES.map((k) => (
                <button key={k} className="block w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800" onClick={() => submit(t(k))}>
                  {t(k)}
                </button>
              ))}
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={m.id ?? `p${i}`} className={clsx('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              <div className={clsx('max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm',
                m.role === 'user' ? 'rounded-br-sm bg-brand-600 text-white' : 'rounded-bl-sm bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100')}>
                {m.content}
                {m.tool_calls && m.tool_calls.length > 0 && (
                  <p className="mt-1 text-[10px] opacity-60">{t('chat.usedTools')}: {m.tool_calls.map((c) => c.name).join(', ')}</p>
                )}
              </div>
            </div>
          ))}
          {send.isPending && <p className="text-xs text-slate-400" aria-live="polite">{t('chat.thinking')}</p>}
          <div ref={end} />
        </div>
        <form className="flex gap-2 border-t border-slate-200 p-3 dark:border-slate-800" onSubmit={(e) => { e.preventDefault(); submit(text); }}>
          <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder={t('chat.placeholder')} aria-label={t('chat.placeholder')} maxLength={1000} />
          <button type="submit" className="rounded-lg bg-brand-600 px-3 text-white disabled:opacity-50" disabled={!text.trim() || send.isPending} aria-label={t('common.submit')}>
            <Send className="h-4 w-4" />
          </button>
        </form>
      </aside>
    </div>
  );
}
