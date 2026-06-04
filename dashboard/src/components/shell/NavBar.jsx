'use client'
import { usePathname, useRouter } from 'next/navigation'

const TABS = [
  { label: 'OPS CENTER',    path: '/' },
  { label: 'DRIVER SIM',   path: '/driver' },
  { label: 'FLEET',        path: '/fleet' },
  { label: 'ML INSIGHTS',  path: '/ml' },
  { label: 'SYSTEM HEALTH', path: '/health' },
]

export default function NavBar() {
  const pathname = usePathname()
  const router   = useRouter()

  return (
    <div
      className="flex items-end gap-0 border-b border-ops-border shrink-0 px-2"
      style={{ background: '#0a1018', height: 32 }}
    >
      {TABS.map(({ label, path }) => {
        const active = pathname === path
        return (
          <button
            key={path}
            onClick={() => router.push(path)}
            style={{
              background:   'none',
              border:       'none',
              borderBottom: active ? '2px solid #00d4ff' : '2px solid transparent',
              color:        active ? '#00d4ff' : '#4a6280',
              cursor:       'pointer',
              fontFamily:   'JetBrains Mono, Courier New, monospace',
              fontSize:     10,
              fontWeight:   active ? 700 : 400,
              letterSpacing: '0.08em',
              padding:      '0 12px 4px',
              height:       '100%',
              transition:   'color 0.15s, border-color 0.15s',
              whiteSpace:   'nowrap',
            }}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
