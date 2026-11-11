import { Camera, ScanLine } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button, Modal } from './ui';

interface Props {
  open: boolean;
  onClose: () => void;
  onDetected: (code: string) => void;
}

/** Camera barcode/QR scanner (laptop webcam or phone camera) with a typed-code fallback. */
export function ScannerModal({ open, onClose, onDetected }: Props) {
  const { t } = useTranslation();
  const regionId = `scan-${useId().replace(/:/g, '')}`;
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState('');
  const stopRef = useRef<(() => Promise<void>) | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    (async () => {
      try {
        const { Html5Qrcode, Html5QrcodeSupportedFormats: F } = await import('html5-qrcode');
        if (cancelled) return;
        const scanner = new Html5Qrcode(regionId, {
          verbose: false,
          formatsToSupport: [F.QR_CODE, F.CODE_128, F.EAN_13, F.EAN_8, F.UPC_A, F.UPC_E, F.CODE_39],
        });
        let done = false;
        await scanner.start(
          { facingMode: 'environment' },
          {
            fps: 10,
            qrbox: (w: number, h: number) => ({
              width: Math.min(w, 320) * 0.9,
              height: Math.min(h, 220) * 0.8,
            }),
          },
          (text: string) => {
            if (done) return;
            done = true;
            if (navigator.vibrate) navigator.vibrate(80);
            onDetected(text.trim());
          },
          () => undefined,
        );
        stopRef.current = async () => {
          try {
            await scanner.stop();
            scanner.clear();
          } catch {
            /* already stopped */
          }
        };
        if (cancelled) await stopRef.current();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      void stopRef.current?.();
      stopRef.current = null;
    };
  }, [open, regionId, onDetected]);

  const submitManual = (e: React.FormEvent) => {
    e.preventDefault();
    if (manual.trim()) onDetected(manual.trim());
    setManual('');
  };

  return (
    <Modal open={open} onClose={onClose} title={t('scan.title')}>
      <div className="space-y-3">
        <div id={regionId} className="aspect-video w-full overflow-hidden rounded-lg bg-slate-900" />
        {error && (
          <p className="flex items-start gap-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200">
            <Camera className="mt-0.5 h-4 w-4 shrink-0" />
            {t('scan.cameraError')} ({error})
          </p>
        )}
        <form className="flex gap-2" onSubmit={submitManual}>
          <input
            className="input"
            placeholder={t('scan.manual')}
            value={manual}
            onChange={(e) => setManual(e.target.value)}
            aria-label={t('scan.manual')}
            autoFocus={!!error}
          />
          <Button type="submit" variant="secondary">
            {t('common.apply')}
          </Button>
        </form>
      </div>
    </Modal>
  );
}

export function ScanButton({ onClick, label }: { onClick: () => void; label?: string }) {
  const { t } = useTranslation();
  return (
    <Button
      variant="secondary"
      onClick={onClick}
      icon={<ScanLine className="h-4 w-4" />}
      aria-label={label ?? t('scan.button')}
    >
      <span className="hidden sm:inline">{label ?? t('scan.button')}</span>
    </Button>
  );
}
