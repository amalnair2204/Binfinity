import { describe, it, expect, beforeEach } from 'vitest'
import { act } from '@testing-library/react'

// Import after test env is set up — store is a module-level singleton
let store
beforeEach(async () => {
  // Re-import fresh store per test by resetting module cache
  vi.resetModules()
  const mod = await import('../store/dashboardStore')
  store = mod.default
  // Reset to initial state
  act(() => {
    store.setState({
      bins: null, zones: null, routes: [], trucks: [],
      fleetStats: null, mlPredictions: [], alerts: [],
      selectedBinId: null, selectedTruckId: null,
      wsStatus: 'disconnected',
      layerVisibility: { bins: true, trucks: true, routes: true, heatmap: false },
      mapFlyTarget: null,
    })
  })
})

describe('basic setters', () => {
  it('setFleetStats updates fleetStats', () => {
    const fs = { total: 50, flagged: 3 }
    act(() => store.getState().setFleetStats(fs))
    expect(store.getState().fleetStats).toEqual(fs)
  })

  it('setRoutes replaces routes array', () => {
    const routes = [{ route_id: 'r1' }, { route_id: 'r2' }]
    act(() => store.getState().setRoutes(routes))
    expect(store.getState().routes).toHaveLength(2)
  })

  it('setWsStatus updates wsStatus', () => {
    act(() => store.getState().setWsStatus('connected'))
    expect(store.getState().wsStatus).toBe('connected')
  })
})

describe('prependAlert', () => {
  it('prepends to alerts array', () => {
    const a1 = { event_id: 'e1', event_type: 'overflow_alert', priority: 3 }
    const a2 = { event_id: 'e2', event_type: 'tip_over', priority: 3 }
    act(() => store.getState().prependAlert(a1))
    act(() => store.getState().prependAlert(a2))
    const { alerts } = store.getState()
    expect(alerts[0].event_id).toBe('e2')
    expect(alerts[1].event_id).toBe('e1')
  })

  it('caps alerts at 100', () => {
    act(() => {
      for (let i = 0; i < 105; i++) {
        store.getState().prependAlert({ event_id: `e${i}`, event_type: 'tip_over', priority: 1 })
      }
    })
    expect(store.getState().alerts).toHaveLength(100)
  })
})

describe('toggleLayer', () => {
  it('toggles bins layer off', () => {
    act(() => store.getState().toggleLayer('bins'))
    expect(store.getState().layerVisibility.bins).toBe(false)
  })

  it('toggles heatmap on from default off', () => {
    act(() => store.getState().toggleLayer('heatmap'))
    expect(store.getState().layerVisibility.heatmap).toBe(true)
  })

  it('double toggle returns to original state', () => {
    act(() => store.getState().toggleLayer('trucks'))
    act(() => store.getState().toggleLayer('trucks'))
    expect(store.getState().layerVisibility.trucks).toBe(true)
  })
})

describe('updateTruckPosition', () => {
  it('updates position of matching truck', () => {
    act(() =>
      store.getState().setTrucks([
        { truck_id: 'T1', position: { lat: 0, lng: 0 } },
        { truck_id: 'T2', position: { lat: 1, lng: 1 } },
      ])
    )
    act(() => store.getState().updateTruckPosition('T1', 51.5, -0.1))
    const t1 = store.getState().trucks.find((t) => t.truck_id === 'T1')
    expect(t1.position).toEqual({ lat: 51.5, lng: -0.1 })
  })

  it('leaves other trucks unchanged', () => {
    act(() =>
      store.getState().setTrucks([
        { truck_id: 'T1', position: { lat: 0, lng: 0 } },
        { truck_id: 'T2', position: { lat: 5, lng: 5 } },
      ])
    )
    act(() => store.getState().updateTruckPosition('T1', 10, 10))
    const t2 = store.getState().trucks.find((t) => t.truck_id === 'T2')
    expect(t2.position).toEqual({ lat: 5, lng: 5 })
  })
})

describe('setMapFlyTarget', () => {
  it('stores fly target', () => {
    const target = { center: [-0.1, 51.5], zoom: 14 }
    act(() => store.getState().setMapFlyTarget(target))
    expect(store.getState().mapFlyTarget).toEqual(target)
  })

  it('can be cleared to null', () => {
    act(() => store.getState().setMapFlyTarget({ center: [0, 0] }))
    act(() => store.getState().setMapFlyTarget(null))
    expect(store.getState().mapFlyTarget).toBeNull()
  })
})
