import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Card, Checkbox, Input, Select } from '@/components/ui';
import { api } from '@/lib/api';
import { formatINR } from '@/lib/format';
import { useToast } from '@/lib/toast';

interface Rule {
  min_amount: number;
  max_amount: number | null;
  approver_role: string | null;
  auto_approve: boolean;
}

export default function ApprovalRules({ editable }: { editable: boolean }) {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['approval-rules'], queryFn: () => api.get<Rule[]>('/approval-rules') });
  const [rules, setRules] = useState<Rule[]>([]);
  const [probe, setProbe] = useState('25000');
  useEffect(() => { if (q.data) setRules(q.data.map(({ min_amount, max_amount, approver_role, auto_approve }) => ({ min_amount, max_amount, approver_role, auto_approve }))); }, [q.data]);
  const route = useQuery({ queryKey: ['approval-route', probe, q.data], queryFn: () => api.get<{ levels: string[] }>('/approval-rules/route', { amount: Number(probe) || 0 }) });
  const save = useMutation({
    mutationFn: () => api.put<Rule[]>('/approval-rules', rules),
    onSuccess: () => { toast.success(t('common.saved')); void qc.invalidateQueries({ queryKey: ['approval-rules'] }); },
    onError: (e) => toast.error(e),
  });
  const set = (i: number, patch: Partial<Rule>) => setRules((rs) => rs.map((r, j) => {
    if (j === i) return { ...r, ...patch };
    if (j === i + 1 && patch.max_amount !== undefined && patch.max_amount !== null) return { ...r, min_amount: patch.max_amount };
    return r;
  }));
  return (
    <Card title={t('rules.title')} actions={editable && <Button loading={save.isPending} onClick={() => save.mutate()}>{t('common.save')}</Button>}>
      <p className="mb-3 text-xs text-slate-500">{t('rules.hint')}</p>
      <div className="space-y-2">
        {rules.map((r, i) => (
          <div key={i} className="grid grid-cols-2 items-end gap-2 rounded-lg border border-slate-200 p-2 dark:border-slate-700 sm:grid-cols-[1fr_1fr_1fr_auto_auto]">
            <Input label={t('rules.from')} type="number" value={r.min_amount} disabled />
            <Input label={t('rules.upTo')} type="number" value={r.max_amount ?? ''} placeholder="∞" disabled={!editable}
              onChange={(e) => set(i, { max_amount: e.target.value === '' ? null : Number(e.target.value) })} />
            <Select label={t('rules.approver')} value={r.approver_role ?? ''} disabled={!editable || r.auto_approve} placeholder="—"
              onChange={(e) => set(i, { approver_role: e.target.value || null })}
              options={[{ value: 'manager', label: t('roles.manager') }, { value: 'admin', label: t('rules.managerAdmin') }]} />
            <Checkbox label={t('rules.auto')} checked={r.auto_approve} disabled={!editable} onChange={(v) => set(i, { auto_approve: v, approver_role: v ? null : 'manager' })} />
            {editable && rules.length > 1 && (
              <Button variant="ghost" aria-label={t('common.remove')} onClick={() => setRules((rs) => rs.filter((_, j) => j !== i).map((x, j, arr) => (j === arr.length - 1 ? { ...x, max_amount: null } : x)))}>
                <Trash2 className="h-4 w-4 text-rose-600" />
              </Button>
            )}
          </div>
        ))}
      </div>
      {editable && (
        <Button className="mt-2" size="sm" variant="secondary" icon={<Plus className="h-4 w-4" />}
          onClick={() => setRules((rs) => {
            const last = rs[rs.length - 1];
            const split = (last?.min_amount ?? 0) + 10000;
            return [...rs.slice(0, -1), { ...last, max_amount: split }, { min_amount: split, max_amount: null, approver_role: 'admin', auto_approve: false }];
          })}>{t('rules.add')}</Button>
      )}
      <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-slate-200 pt-3 dark:border-slate-700">
        <Input className="w-40" label={t('rules.test')} type="number" value={probe} onChange={(e) => setProbe(e.target.value)} />
        <p className="pb-2 text-sm">{formatINR(Number(probe) || 0)} → {route.data?.levels.length ? route.data.levels.map((l) => <Badge key={l} tone="amber" className="mr-1">{t(`roles.${l}`)}</Badge>) : <Badge tone="green">{t('rules.auto')}</Badge>}</p>
      </div>
    </Card>
  );
}
