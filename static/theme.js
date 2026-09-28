/**
 * 极简现代主题管理系统：支持深浅明暗模式与多色强调色切换
 */
(function() {
  const savedMode = localStorage.getItem('gw_theme_mode') || 'dark';
  const isDark = savedMode === 'dark' || (savedMode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  if (isDark) {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
  const defaultAccent = document.documentElement.getAttribute('data-default-accent') || 'emerald';
  const savedAccent = localStorage.getItem('gw_accent_color') || defaultAccent;
  document.documentElement.setAttribute('data-accent', savedAccent);
})();

function createThemeManager(defaultAccent = 'emerald') {
  return {
    themeMode: localStorage.getItem('gw_theme_mode') || 'dark',
    accentColor: localStorage.getItem('gw_accent_color') || defaultAccent,
    showThemeMenu: false,

    colorOptions: [
      { id: 'emerald', name: '翡翠绿', hex: '#10b981' },
      { id: 'indigo', name: '极客蓝', hex: '#6366f1' },
      { id: 'violet', name: '紫罗兰', hex: '#8b5cf6' },
      { id: 'amber', name: '琥珀金', hex: '#f59e0b' },
      { id: 'cyan', name: '电光青', hex: '#06b6d4' },
      { id: 'rose', name: '玫瑰绯', hex: '#f43f5e' },
      { id: 'zinc', name: '黑白调', hex: '#71717a' },
    ],

    initTheme() {
      this.syncThemeDom();
      try {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
          if (this.themeMode === 'system') this.syncThemeDom();
        });
      } catch (e) {}
    },

    setThemeMode(mode) {
      this.themeMode = mode;
      localStorage.setItem('gw_theme_mode', mode);
      this.syncThemeDom();
    },

    toggleThemeMode() {
      const next = this.themeMode === 'dark' ? 'light' : 'dark';
      this.setThemeMode(next);
    },

    setAccent(color) {
      this.accentColor = color;
      localStorage.setItem('gw_accent_color', color);
      this.syncThemeDom();
    },

    syncThemeDom() {
      const root = document.documentElement;
      const isDark = this.themeMode === 'dark' || (this.themeMode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
      if (isDark) {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
      root.setAttribute('data-accent', this.accentColor);
    }
  };
}
