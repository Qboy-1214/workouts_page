import { useState } from 'react';
import type { Activity } from '../types';
import type { GoalConfig } from '../core/config';
import { sportEmoji } from '../core/sportTypes';
import {
  getGoal,
  saveGoalOverrides,
  clearGoalOverrides,
} from '../core/goalSettings';
import { useLocale } from '../hooks/useLocale';

const GOAL_FIELDS: { key: keyof GoalConfig; label: string }[] = [
  { key: 'weekly', label: '周' },
  { key: 'monthly', label: '月' },
  { key: 'yearly', label: '年' },
];

export function GoalSettingsModal({
  activities,
  onClose,
}: {
  activities: Activity[];
  onClose: () => void;
}) {
  const { locale } = useLocale();
  const zh = locale === 'zh';

  const sports = ['all', ...[...new Set(activities.map((a) => a.type))].sort()];
  const [draft, setDraft] = useState<Record<string, Record<string, string>>>(
    () => {
      const init: Record<string, Record<string, string>> = {};
      for (const s of sports) {
        const g = getGoal(s);
        init[s] = {
          weekly: String(g.weekly),
          monthly: String(g.monthly),
          yearly: String(g.yearly),
        };
      }
      return init;
    },
  );

  const setValue = (sport: string, key: string, value: string) => {
    setDraft((d) => ({ ...d, [sport]: { ...d[sport], [key]: value } }));
  };

  const save = () => {
    const overrides: Record<string, Record<string, number>> = {};
    for (const sport of sports) {
      const row = draft[sport];
      const yearly = parseFloat(row.yearly);
      const monthly = parseFloat(row.monthly);
      const weekly = parseFloat(row.weekly);
      if ([yearly, monthly, weekly].some((n) => Number.isNaN(n))) continue;
      overrides[sport] = { yearly, monthly, weekly };
    }
    saveGoalOverrides(overrides);
    onClose();
  };

  const reset = () => {
    clearGoalOverrides();
    onClose();
  };

  const nameLabel = (sport: string) =>
    sport === 'all'
      ? zh
        ? '全部运动'
        : 'All sports'
      : `${sportEmoji(sport)} ${sport}`;

  const inputClass =
    'w-14 border-b-[0.5px] border-[var(--color-border)] bg-transparent py-1 text-right text-sm text-[var(--color-text)] outline-none focus:border-[var(--color-accent)]';

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="w-full max-w-md rounded-xl border-[0.5px] border-[var(--color-border)] bg-[var(--color-card)] p-5"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={zh ? '目标设置' : 'Goal settings'}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-semibold">
            {zh ? '目标设置' : 'Goal settings'}
          </h2>
          <button
            onClick={onClose}
            aria-label={zh ? '关闭' : 'Close'}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[var(--color-muted)] hover:bg-[var(--color-bg)] hover:text-[var(--color-text)]"
          >
            ✕
          </button>
        </div>

        <div className="mb-1 grid grid-cols-[1fr_repeat(3,4rem)] gap-x-3 text-xs text-[var(--color-muted)]">
          <span>{zh ? '运动' : 'Sport'}</span>
          {GOAL_FIELDS.map((f) => (
            <span key={f.key} className="text-right">
              {f.label}
            </span>
          ))}
        </div>

        <div className="space-y-3">
          {sports.map((sport) => (
            <div
              key={sport}
              className="grid grid-cols-[1fr_repeat(3,4rem)] items-center gap-x-3"
            >
              <span className="truncate text-sm">
                {sport === 'all' ? nameLabel(sport) : sport}
              </span>
              {GOAL_FIELDS.map((f) => (
                <input
                  key={f.key}
                  type="number"
                  min={0}
                  inputMode="decimal"
                  className={inputClass}
                  value={draft[sport]?.[f.key] ?? ''}
                  onChange={(e) => setValue(sport, f.key, e.target.value)}
                  aria-label={`${nameLabel(sport)} ${f.label}`}
                />
              ))}
            </div>
          ))}
        </div>

        <p className="mt-1 text-xs text-[var(--color-muted)]">km</p>

        <div className="mt-4 flex items-center justify-between">
          <button
            onClick={reset}
            className="text-xs text-[var(--color-muted)] hover:text-[var(--color-text)]"
          >
            {zh ? '恢复默认' : 'Reset to defaults'}
          </button>
          <button
            onClick={save}
            className="rounded-full px-4 py-1.5 text-sm font-medium text-[var(--color-on-accent)] bg-[var(--color-accent)] hover:opacity-90"
          >
            {zh ? '保存' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
