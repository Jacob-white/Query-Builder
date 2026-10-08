import "@testing-library/jest-dom";

/**
 * Newer Node versions ship a built-in Web Storage global that is unusable without
 * `--localstorage-file`; it shadows jsdom's implementation under vitest. Install an
 * in-memory Storage so tests behave the same on every Node version.
 */
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null;
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

for (const name of ["localStorage", "sessionStorage"] as const) {
  let usable = false;
  try {
    const existing = globalThis[name];
    usable = !!existing && typeof existing.getItem === "function";
  } catch {
    usable = false;
  }
  if (!usable) {
    const storage = new MemoryStorage();
    Object.defineProperty(globalThis, name, { value: storage, configurable: true, writable: true });
    if (typeof window !== "undefined" && window !== (globalThis as unknown)) {
      Object.defineProperty(window, name, { value: storage, configurable: true, writable: true });
    }
  }
}
