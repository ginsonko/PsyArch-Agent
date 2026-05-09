export function asArray<T = any>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function asNumber(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

export function formatNumber(value: unknown, digits = 3): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  if (Math.abs(n) >= 1000) return n.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
  return n.toFixed(digits).replace(/\.?0+$/, '');
}

export function formatCount(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return Math.round(n).toLocaleString('zh-CN');
}

export function formatPercent(value: unknown, digits = 1): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `${(n * 100).toFixed(digits)}%`;
}

export function formatDuration(ms: unknown): string {
  const n = asNumber(ms, 0);
  if (n <= 0) return '0 ms';
  if (n < 1000) return `${Math.round(n)} ms`;
  const sec = n / 1000;
  if (sec < 60) return `${sec.toFixed(1)} s`;
  const min = Math.floor(sec / 60);
  const rest = Math.round(sec % 60);
  return `${min}m ${rest}s`;
}

export function shortText(value: unknown, max = 80): string {
  const text = readableApObjectText(value);
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

export function readableApObjectText(value: unknown): string {
  const text = String(value ?? '');
  if (!text.includes('+')) return text;
  let out = '';
  let depth = 0;
  for (let index = 0; index < text.length; index += 1) {
    const ch = text[index];
    if (ch === '{') {
      depth += 1;
      out += ch;
      continue;
    }
    if (ch === '}') {
      depth = Math.max(0, depth - 1);
      out += ch;
      continue;
    }
    if (ch === '+' && depth > 0) {
      out = out.replace(/\s+$/, '');
      out += ' ';
      while (index + 1 < text.length && /\s/.test(text[index + 1] || '')) index += 1;
      continue;
    }
    out += ch;
  }
  return out;
}

export function shortDisplayText(value: unknown, max = 80): string {
  return shortText(readableApObjectText(value), max);
}

export function jsonPretty(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return String(value ?? '');
  }
}

export function pick(obj: any, paths: string[], fallback: any = undefined): any {
  for (const path of paths) {
    const parts = path.split('.');
    let current = obj;
    let ok = true;
    for (const part of parts) {
      if (current && Object.prototype.hasOwnProperty.call(current, part)) {
        current = current[part];
      } else {
        ok = false;
        break;
      }
    }
    if (ok && current !== undefined && current !== null) return current;
  }
  return fallback;
}
