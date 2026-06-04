import { describe, it, expect, beforeEach } from 'vitest'
import { act } from 'react'

// Import the raw store creator so we get a fresh instance per test
let useStore

beforeEach(async () => {
  vi.resetModules()
  const mod = await import('../store/driverStore.js')
  useStore = mod.default
  // Reset to clean state
  act(() => {
    useStore.setState({
      truckId: null,
      allStops: [],
      currentStop: null,
      nextStop: null,
      stopsCompleted: 0,
      loadLiters: 0,
      capacityLiters: 10_000,
      status: 'unknown',
      position: null,
      shiftStarted: false,
      shiftEnded: false,
      binsCollectedToday: 0,
      litersCollectedToday: 0,
      alerts: [],
      isConnected: false,
      isOnline: true,
    })
  })
})

describe('driverStore', () => {
  describe('setRoute', () => {
    it('filters out depot stops', () => {
      const stops = [
        { node_id: 'D1', node_type: 'depot' },
        { node_id: 'B1', node_type: 'bin' },
        { node_id: 'B2', node_type: 'bin' },
      ]
      act(() => useStore.getState().setRoute(stops))
      const s = useStore.getState()
      expect(s.allStops).toHaveLength(2)
      expect(s.currentStop.node_id).toBe('B1')
      expect(s.nextStop.node_id).toBe('B2')
    })

    it('resets stopsCompleted to 0', () => {
      act(() => useStore.setState({ stopsCompleted: 3 }))
      act(() => useStore.getState().setRoute([{ node_id: 'B1', node_type: 'bin' }]))
      expect(useStore.getState().stopsCompleted).toBe(0)
    })

    it('handles empty stop list', () => {
      act(() => useStore.getState().setRoute([]))
      const s = useStore.getState()
      expect(s.allStops).toHaveLength(0)
      expect(s.currentStop).toBeNull()
      expect(s.nextStop).toBeNull()
    })

    it('handles null input without throwing', () => {
      act(() => useStore.getState().setRoute(null))
      expect(useStore.getState().allStops).toHaveLength(0)
    })
  })

  describe('advanceStop', () => {
    it('removes head stop and increments stopsCompleted', () => {
      const stops = [
        { node_id: 'B1', node_type: 'bin' },
        { node_id: 'B2', node_type: 'bin' },
      ]
      act(() => useStore.getState().setRoute(stops))
      act(() => useStore.getState().advanceStop(0))
      const s = useStore.getState()
      expect(s.allStops).toHaveLength(1)
      expect(s.currentStop.node_id).toBe('B2')
      expect(s.nextStop).toBeNull()
      expect(s.stopsCompleted).toBe(1)
    })

    it('increments binsCollectedToday for bin stops', () => {
      act(() => useStore.getState().setRoute([{ node_id: 'B1', node_type: 'bin' }]))
      act(() => useStore.getState().advanceStop(100))
      const s = useStore.getState()
      expect(s.binsCollectedToday).toBe(1)
      expect(s.litersCollectedToday).toBe(100)
    })

    it('does NOT increment binsCollectedToday for dump_yard stops', () => {
      act(() => useStore.getState().setRoute([{ node_id: 'Y1', node_type: 'dump_yard' }]))
      act(() => useStore.getState().advanceStop(0))
      expect(useStore.getState().binsCollectedToday).toBe(0)
    })
  })

  describe('startShift / endShift', () => {
    it('startShift resets counters', () => {
      act(() => {
        useStore.setState({ binsCollectedToday: 5, litersCollectedToday: 500, shiftEnded: true })
        useStore.getState().startShift()
      })
      const s = useStore.getState()
      expect(s.shiftStarted).toBe(true)
      expect(s.shiftEnded).toBe(false)
      expect(s.binsCollectedToday).toBe(0)
      expect(s.litersCollectedToday).toBe(0)
    })

    it('endShift sets shiftEnded to true', () => {
      act(() => useStore.getState().endShift())
      expect(useStore.getState().shiftEnded).toBe(true)
    })
  })

  describe('alerts', () => {
    it('addAlert prepends and caps at 10', () => {
      act(() => {
        for (let i = 0; i < 12; i++) {
          useStore.getState().addAlert({ id: i, type: 'overflow', message: `msg ${i}` })
        }
      })
      expect(useStore.getState().alerts).toHaveLength(10)
      // Most recent is first
      expect(useStore.getState().alerts[0].id).toBe(11)
    })

    it('dismissAlert removes by id', () => {
      act(() => {
        useStore.getState().addAlert({ id: 1, type: 'overflow', message: 'a' })
        useStore.getState().addAlert({ id: 2, type: 'reroute', message: 'b' })
        useStore.getState().dismissAlert(1)
      })
      const alerts = useStore.getState().alerts
      expect(alerts).toHaveLength(1)
      expect(alerts[0].id).toBe(2)
    })
  })
})
