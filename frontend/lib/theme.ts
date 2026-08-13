export const THEME_STORAGE_KEY = "newscraft-theme"

export type Theme = "light" | "dark"

export const THEME_BOOTSTRAP_SCRIPT = `(() => {
  const root = document.documentElement;
  let stored = null;
  try {
    stored = window.localStorage.getItem("${THEME_STORAGE_KEY}");
  } catch {}
  const theme = stored === "light" || stored === "dark"
    ? stored
    : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  root.classList.toggle("dark", theme === "dark");
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
})();`

export function isTheme(value: string | null): value is Theme {
  return value === "light" || value === "dark"
}
