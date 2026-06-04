'use client'
import TopBar      from './TopBar'
import NavBar      from './NavBar'
import Sidebar     from './Sidebar'
import { useFleetStats }        from '../../hooks/useFleetStats'
import { useBinGeoJSON }        from '../../hooks/useBinGeoJSON'
import { useRoutes }            from '../../hooks/useRoutes'
import { useTrucks }            from '../../hooks/useTrucks'
import { useMLPredictions }     from '../../hooks/useMLPredictions'
import { useAlertFeed }         from '../../hooks/useAlertFeed'
import { useDashboardSocket }   from '../../hooks/useDashboardSocket'
import { useKeyboardShortcuts } from '../../hooks/useKeyboardShortcuts'

export default function AppShell({ children }) {
  useFleetStats()
  useBinGeoJSON()
  useRoutes()
  useTrucks()
  useMLPredictions()
  useAlertFeed()
  useDashboardSocket()
  useKeyboardShortcuts()

  return (
    <div
      className="flex flex-col bg-ops-bg text-ops-text"
      style={{ height: '100vh', overflow: 'hidden' }}
    >
      <TopBar />
      <NavBar />

      <div className="flex flex-1 overflow-hidden" style={{ minHeight: 0 }}>
        <Sidebar />
        <div className="flex-1 overflow-hidden" style={{ minWidth: 0 }}>
          {children}
        </div>
      </div>
    </div>
  )
}
