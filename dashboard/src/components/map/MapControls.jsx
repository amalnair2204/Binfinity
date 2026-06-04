'use client'
import useDashboardStore from '../../store/dashboardStore'

const CONTROLS = [
  { key: 'heatmap', label: 'H', title: 'Heatmap (H)' },
  { key: 'bins',    label: 'B', title: 'Bins (B)'    },
  { key: 'trucks',  label: 'T', title: 'Trucks (T)'  },
  { key: 'routes',  label: 'R', title: 'Routes (R)'  },
]

export default function MapControls() {
  const layerVisibility = useDashboardStore((s) => s.layerVisibility)
  const toggleLayer     = useDashboardStore((s) => s.toggleLayer)

  return (
    <div className="absolute flex flex-col gap-1 z-10" style={{ top: 12, right: 12 }}>
      {CONTROLS.map(({ key, label, title }) => {
        const on = layerVisibility[key]
        return (
          <button
            key={key}
            title={title}
            onClick={() => toggleLayer(key)}
            className="w-7 h-7 rounded text-xs font-mono font-bold border transition-colors"
            style={{
              background:   on ? 'rgba(0,212,255,0.15)' : 'rgba(13,21,32,0.9)',
              borderColor:  on ? '#00d4ff' : '#1a2535',
              color:        on ? '#00d4ff' : '#4a6280',
            }}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
