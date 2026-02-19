(function () {
  const STORAGE_KEY = "zzcat_theme";
  const THEMES = ["default", "pinky", "light-green"];

  function syncBodyThemeClass(theme) {
    if (!document.body) return;
    Array.from(document.body.classList)
      .filter(function (cls) {
        return cls.indexOf("theme-") === 0;
      })
      .forEach(function (cls) {
        document.body.classList.remove(cls);
      });
    document.body.classList.add("theme-" + theme);
  }

  function applyTheme(theme) {
    const next = THEMES.includes((theme || "").toLowerCase()) ? theme.toLowerCase() : "default";
    document.documentElement.setAttribute("data-theme", next);
    syncBodyThemeClass(next);
    localStorage.setItem(STORAGE_KEY, next);
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme: next } }));
  }

  function currentTheme() {
    const saved = (localStorage.getItem(STORAGE_KEY) || "default").toLowerCase();
    return THEMES.includes(saved) ? saved : "default";
  }

  function mountSwitcher() {
    if (document.getElementById("theme-dock")) return;
    const wrap = document.createElement("div");
    wrap.id = "theme-dock";
    wrap.className = "theme-dock";
    wrap.innerHTML = '<label for="theme-select">Theme</label><select id="theme-select"><option value="default">Default</option><option value="pinky">Pinky</option><option value="light-green">Light Green</option></select>';
    document.body.appendChild(wrap);
    const select = document.getElementById("theme-select");
    select.value = currentTheme();
    select.addEventListener("change", function () {
      applyTheme(select.value);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyTheme(currentTheme());
    mountSwitcher();
  });

  // Fallback for pages where DOMContentLoaded already fired before script execution.
  if (document.readyState === "interactive" || document.readyState === "complete") {
    applyTheme(currentTheme());
    mountSwitcher();
  }
})();
