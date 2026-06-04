export function fillColor(pct) {
  if (pct >= 90) return '#ff3355'
  if (pct >= 75) return '#ff6600'
  if (pct >= 50) return '#ffaa00'
  return '#00ff88'
}

export function fillColorDim(pct) {
  if (pct >= 90) return '#7a1a2a'
  if (pct >= 75) return '#7a3300'
  if (pct >= 50) return '#7a5200'
  return '#006633'
}

export function fillLabel(pct) {
  if (pct >= 90) return 'CRITICAL'
  if (pct >= 75) return 'WARNING'
  if (pct >= 50) return 'WATCH'
  return 'NOMINAL'
}

export const FILL_LEGEND = [
  { label: '0–50%',   color: '#00ff88', desc: 'NOMINAL'  },
  { label: '50–75%',  color: '#ffaa00', desc: 'WATCH'    },
  { label: '75–90%',  color: '#ff6600', desc: 'WARNING'  },
  { label: '90–100%', color: '#ff3355', desc: 'CRITICAL' },
]
