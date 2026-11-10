import { useSyncExternalStore } from 'react';
import { GOALS, DEFAULT_GOAL } from './config';
import type { GoalConfig } from './config';

const KEY = 'fitpage.goal-overrides';
const listeners = new Set<() => void>();
let overridesCache: Record<string, Partial<GoalConfig>> | null = null;
const mergedCache = new Map<string, GoalConfig>();

function loadOverrides(): Record<string, Partial<GoalConfig>> {
  if (overridesCache) return overridesCache;
  try {
    overridesCache =
      (JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<
        string,
        Partial<GoalConfig>
      >) ?? {};
  } catch {
    overridesCache = {};
  }
  return overridesCache;
}

/** 保存各运动的目标覆盖（km），并通知所有订阅者刷新 */
export function saveGoalOverrides(
  overrides: Record<string, Partial<GoalConfig>>,
) {
  localStorage.setItem(KEY, JSON.stringify(overrides));
  overridesCache = overrides;
  mergedCache.clear();
  listeners.forEach((l) => l());
}

/** 清除全部覆盖，恢复 config.yml 默认值 */
export function clearGoalOverrides() {
  localStorage.removeItem(KEY);
  overridesCache = {};
  mergedCache.clear();
  listeners.forEach((l) => l());
}

export function subscribeGoals(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 当前运动的目标：config.yml 默认值 + localStorage 覆盖。快照稳定引用 */
export function getGoal(type: string): GoalConfig {
  if (!mergedCache.has(type)) {
    const base = GOALS[type] ?? DEFAULT_GOAL;
    const o = loadOverrides()[type] ?? {};
    mergedCache.set(type, {
      yearly: o.yearly ?? base.yearly,
      monthly: o.monthly ?? base.monthly,
      weekly: o.weekly ?? base.weekly,
      unit: base.unit,
    });
  }
  return mergedCache.get(type)!;
}

/** 读取某运动的目标原始值（含是否为覆盖项），供设置面板初始化 */
export function getGoalDraft(type: string): GoalConfig {
  return getGoal(type);
}

export function hasGoalOverrides(): boolean {
  return Object.keys(loadOverrides()).length > 0;
}

/** React 订阅：目标变化时组件自动重渲染 */
export function useGoal(type: string): GoalConfig {
  return useSyncExternalStore(
    subscribeGoals,
    () => getGoal(type),
    () => getGoal(type),
  );
}
