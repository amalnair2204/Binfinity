/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'ops-bg':      '#080c10',
        'ops-surface': '#0d1520',
        'ops-border':  '#1a2535',
        'ops-green':   '#00ff88',
        'ops-amber':   '#ffaa00',
        'ops-orange':  '#ff6600',
        'ops-red':     '#ff3355',
        'ops-cyan':    '#00d4ff',
        'ops-text':    '#c8d8e8',
        'ops-muted':   '#4a6280',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Courier New', 'monospace'],
      },
    },
  },
  plugins: [],
}
