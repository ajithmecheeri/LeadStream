export type Weights = Record<string, number>;

export const total = (w: Weights) => Object.values(w).reduce((a, b) => a + b, 0);

/**
 * Set one factor and spread the difference over the others (proportionally, in whole numbers)
 * so the total stays 100. Factors at 0 stay at 0 unless everything else is 0 too.
 */
export function setWeight(w: Weights, key: string, value: number): Weights {
  const v = Math.max(0, Math.min(60, Math.round(value)));
  const others = Object.keys(w).filter((k) => k !== key);
  const next: Weights = { ...w, [key]: v };
  let diff = 100 - total(next);
  if (diff === 0 || others.length === 0) return next;

  let pool = others.filter((k) => (diff < 0 ? next[k]! > 0 : true));
  const base = pool.reduce((a, k) => a + next[k]!, 0);
  // Proportional pass.
  for (const k of pool) {
    const share = base > 0 ? (next[k]! / base) * diff : diff / pool.length;
    const d = diff > 0 ? Math.floor(share) : Math.ceil(share);
    next[k] = Math.max(0, Math.min(60, next[k]! + d));
  }
  // Settle the remainder one point at a time, largest weights first.
  diff = 100 - total(next);
  for (let guard = 0; diff !== 0 && guard < 1000; guard++) {
    pool = others
      .filter((k) => (diff > 0 ? next[k]! < 60 : next[k]! > 0))
      .sort((a, b) => next[b]! - next[a]!);
    if (pool.length === 0) break;
    const k = pool[guard % pool.length]!;
    next[k] = next[k]! + Math.sign(diff);
    diff -= Math.sign(diff);
  }
  return next;
}
