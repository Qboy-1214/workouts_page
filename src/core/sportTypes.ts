// 运动类型的中文命名与 emoji 映射（未收录的类型回退为原文名 + 🏅）
export const SPORT_TYPES: Record<string, { emoji: string; zh: string }> = {
  Run: { emoji: '🏃', zh: '跑步' },
  'Trail Run': { emoji: '🏃‍♂️', zh: '越野跑' },
  Ride: { emoji: '🚴', zh: '骑行' },
  VirtualRide: { emoji: '🚴‍♂️', zh: '虚拟骑行' },
  Workout: { emoji: '🏋️', zh: '训练' },
  Soccer: { emoji: '⚽', zh: '足球' },
  Badminton: { emoji: '🏸', zh: '羽毛球' },
  'VR Tennis': { emoji: '🎾', zh: 'VR 网球' },
  Hike: { emoji: '🥾', zh: '徒步' },
  Rowing: { emoji: '🚣', zh: '划船' },
  Swim: { emoji: '🏊', zh: '游泳' },
  Kayaking: { emoji: '🛶', zh: '皮划艇' },
  RoadTrip: { emoji: '🚗', zh: '公路旅行' },
  Ski: { emoji: '⛷️', zh: '滑雪' },
  Snowboard: { emoji: '🏂', zh: '单板滑雪' },
  BackcountrySki: { emoji: '🏔️', zh: '野雪滑雪' },
};

export function sportEmoji(type: string): string {
  return SPORT_TYPES[type]?.emoji ?? '🏅';
}

export function sportLabel(type: string, locale?: string): string {
  const entry = SPORT_TYPES[type];
  if (!entry) return `🏅 ${type}`;
  return locale === 'zh' ? `${entry.emoji} ${entry.zh}` : `${entry.emoji} ${type}`;
}

// 室内运动（健身房训练、羽毛球、VR 网球、虚拟骑行等）——其余类型视为室外
export const INDOOR_SPORTS = new Set([
  'Workout',
  'Badminton',
  'VR Tennis',
  'VirtualRide',
]);

export function isIndoorSport(type: string): boolean {
  return INDOOR_SPORTS.has(type);
}
