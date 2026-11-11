import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Upload } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Card, PageHeader, Select, Stat } from '@/components/ui';
import { api } from '@/lib/api';
import { useToast } from '@/lib/toast';

interface ImportType {
  entity: string;
  label: string;
  fields: { name: string; type: string; required: boolean }[];
}
interface UploadRes {
  job_id: number;
  entity: string;
  filename: string;
  columns: string[];
  rows: number;
  sample: Record<string, unknown>[];
  mapping: Record<string, string | null>;
  fields: { name: string; type: string; required: boolean }[];
}
interface Row {
  row: number;
  values: Record<string, unknown>;
  errors: string[];
}
interface Preview {
  total: number;
  valid: number;
  invalid: number;
  rows: Row[];
  error_rows: Row[];
}
interface CommitRes {
  job_id: number;
  created: number;
  updated: number;
  skipped: number;
  error_count: number;
}

export default function Imports() {
  const { t } = useTranslation();
  const toast = useToast();
  const qc = useQueryClient();
  const types = useQuery({
    queryKey: ['imports', 'types'],
    queryFn: () => api.get<ImportType[]>('/imports/types'),
  });
  const [entity, setEntity] = useState('products');
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<UploadRes | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<CommitRes | null>(null);
  const [onlyErrors, setOnlyErrors] = useState(false);

  const reset = () => {
    setJob(null);
    setPreview(null);
    setResult(null);
    setFile(null);
  };
  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append('entity', entity);
      fd.append('file', file!);
      return api.upload<UploadRes>('/imports/upload', fd);
    },
    onSuccess: (r) => {
      setJob(r);
      setMapping(r.mapping);
      setPreview(null);
      setResult(null);
    },
    onError: (e) => toast.error(e),
  });
  const doPreview = useMutation({
    mutationFn: () => api.post<Preview>(`/imports/${job!.job_id}/preview`, { mapping }),
    onSuccess: setPreview,
    onError: (e) => toast.error(e),
  });
  const commit = useMutation({
    mutationFn: () => api.post<CommitRes>(`/imports/${job!.job_id}/commit`, { mapping }),
    onSuccess: (r) => {
      setResult(r);
      toast.success(t('imports.done', { created: r.created, updated: r.updated }));
      void qc.invalidateQueries();
    },
    onError: (e) => toast.error(e),
  });
  const spec = types.data?.find((x) => x.entity === entity);
  const rows = preview ? (onlyErrors ? preview.error_rows : preview.rows) : [];
  const fields = job?.fields ?? spec?.fields ?? [];

  return (
    <div className="space-y-4">
      <PageHeader title={t('nav.imports')} subtitle={t('imports.subtitle')} />
      <Card title={`1. ${t('imports.chooseFile')}`}>
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Select
            label={t('imports.type')}
            value={entity}
            onChange={(e) => {
              setEntity(e.target.value);
              reset();
            }}
            options={(types.data ?? []).map((x) => ({ value: x.entity, label: x.label }))}
          />
          <div>
            <label className="label" htmlFor="import-file">
              {t('imports.file')}
            </label>
            <input
              id="import-file"
              type="file"
              accept=".csv,.xlsx"
              className="input"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <Button
            icon={<Upload className="h-4 w-4" />}
            disabled={!file}
            loading={upload.isPending}
            onClick={() => upload.mutate()}
          >
            {t('imports.upload')}
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-500">{t('imports.templates')}:</span>
          <Button
            size="sm"
            variant="secondary"
            icon={<Download className="h-3.5 w-3.5" />}
            onClick={() => api.download(`/imports/templates/${entity}`, `${entity}_template.csv`)}
          >
            CSV
          </Button>
          <Button
            size="sm"
            variant="secondary"
            icon={<Download className="h-3.5 w-3.5" />}
            onClick={() =>
              api.download(`/imports/templates/${entity}`, `${entity}_template.xlsx`, { fmt: 'xlsx' })
            }
          >
            Excel
          </Button>
          {spec && (
            <span className="text-xs text-slate-500">
              {t('imports.requiredFields')}:{' '}
              {spec.fields
                .filter((f) => f.required)
                .map((f) => f.name)
                .join(', ')}
            </span>
          )}
        </div>
      </Card>

      {job && (
        <Card
          title={`2. ${t('imports.mapColumns')} — ${job.filename} (${job.rows} ${t('imports.rows')})`}
          actions={
            <Button loading={doPreview.isPending} onClick={() => doPreview.mutate()}>
              {t('imports.preview')}
            </Button>
          }
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {fields.map((f) => (
              <Select
                key={f.name}
                label={`${f.name}${f.required ? ' *' : ''} (${f.type})`}
                value={mapping[f.name] ?? ''}
                onChange={(e) => setMapping({ ...mapping, [f.name]: e.target.value || null })}
                placeholder={t('imports.notMapped')}
                options={job.columns.map((c) => ({ value: c, label: c }))}
              />
            ))}
          </div>
        </Card>
      )}

      {preview && (
        <Card
          title={`3. ${t('imports.reviewCommit')}`}
          actions={
            <>
              <label className="flex items-center gap-1.5 text-xs">
                <input
                  type="checkbox"
                  checked={onlyErrors}
                  onChange={(e) => setOnlyErrors(e.target.checked)}
                />
                {t('imports.onlyErrors')}
              </label>
              {!result && (
                <Button
                  variant="success"
                  disabled={!preview.valid}
                  loading={commit.isPending}
                  onClick={() => commit.mutate()}
                >
                  {t('imports.commit', { n: preview.valid })}
                </Button>
              )}
            </>
          }
        >
          <div className="mb-3 grid grid-cols-3 gap-3">
            <Stat label={t('imports.total')} value={preview.total} />
            <Stat label={t('imports.valid')} value={preview.valid} tone="green" />
            <Stat
              label={t('imports.invalid')}
              value={preview.invalid}
              tone={preview.invalid ? 'red' : undefined}
            />
          </div>
          {result && (
            <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg bg-emerald-50 p-3 text-sm dark:bg-emerald-900/20">
              <span>
                {t('imports.result', {
                  created: result.created,
                  updated: result.updated,
                  skipped: result.skipped,
                })}
              </span>
              {result.error_count > 0 && (
                <Button
                  size="sm"
                  variant="secondary"
                  icon={<Download className="h-3.5 w-3.5" />}
                  onClick={() =>
                    api.download(`/imports/${result.job_id}/errors.csv`, `import_${result.job_id}_errors.csv`)
                  }
                >
                  {t('imports.errorReport')}
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={reset}>
                {t('imports.another')}
              </Button>
            </div>
          )}
          <div className="-mx-4 overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr>
                  <th className="th">#</th>
                  {fields.map((f) => (
                    <th key={f.name} className="th">
                      {f.name}
                    </th>
                  ))}
                  <th className="th">{t('imports.errors')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((r) => (
                  <tr key={r.row} className={r.errors.length ? 'bg-rose-50/60 dark:bg-rose-900/10' : ''}>
                    <td className="td">{r.row}</td>
                    {fields.map((f) => (
                      <td key={f.name} className="td">
                        {r.values[f.name] === null || r.values[f.name] === undefined
                          ? ''
                          : String(r.values[f.name])}
                      </td>
                    ))}
                    <td className="td whitespace-normal">
                      {r.errors.length ? (
                        r.errors.map((e) => (
                          <Badge key={e} tone="red" className="mr-1">
                            {e}
                          </Badge>
                        ))
                      ) : (
                        <Badge tone="green">OK</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
