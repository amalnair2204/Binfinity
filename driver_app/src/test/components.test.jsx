import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import React from 'react'

// Shared store state helper
function resetStore(overrides = {}) {
  return {
    truckId: 'T1',
    allStops: [],
    currentStop: null,
    nextStop: null,
    stopsCompleted: 0,
    loadLiters: 0,
    capacityLiters: 10_000,
    status: 'active',
    position: null,
    shiftStarted: true,
    shiftEnded: false,
    binsCollectedToday: 0,
    litersCollectedToday: 0,
    alerts: [],
    isConnected: true,
    isOnline: true,
    advanceStop: vi.fn(),
    dismissAlert: vi.fn(),
    endShift: vi.fn(),
    ...overrides,
  }
}

// Mock the store so tests don't hit localStorage / real zustand
vi.mock('../store/driverStore.js', () => {
  let _state = resetStore()
  const useDriverStore = (selector) => selector(_state)
  useDriverStore.__setState = (s) => { _state = { ..._state, ...s } }
  return { default: useDriverStore }
})

// Mock API client
vi.mock('../api/client.js', () => ({
  api: {
    confirmCollection: vi.fn().mockResolvedValue({ status: 'ok' }),
    confirmDump: vi.fn().mockResolvedValue({ status: 'ok' }),
    getRoute: vi.fn().mockResolvedValue({ stops: [] }),
    getTruckState: vi.fn().mockResolvedValue({ load_liters: 0, capacity_liters: 10_000, status: 'active' }),
    updatePosition: vi.fn().mockResolvedValue({}),
  },
}))

// Mock socket
vi.mock('../api/socket.js', () => ({
  driverSocket: { on: vi.fn(() => () => {}), connect: vi.fn(), disconnect: vi.fn() },
}))

import useDriverStore from '../store/driverStore.js'
import { api } from '../api/client.js'
import { offlineQueue } from '../utils/offlineQueue.js'
import AlertBanner from '../components/AlertBanner.jsx'
import RouteProgress from '../components/RouteProgress.jsx'
import ActionButton from '../components/ActionButton.jsx'

describe('AlertBanner', () => {
  beforeEach(() => useDriverStore.__setState({ alerts: [] }))

  it('renders nothing when there are no alerts', () => {
    const { container } = render(<AlertBanner />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the most recent alert message', () => {
    useDriverStore.__setState({
      alerts: [{ id: 1, type: 'overflow', severity: 'error', message: 'Bin overflow!' }],
    })
    render(<AlertBanner />)
    expect(screen.getByText('Bin overflow!')).toBeInTheDocument()
  })

  it('dismiss button calls dismissAlert with correct id', () => {
    const dismissAlert = vi.fn()
    useDriverStore.__setState({
      alerts: [{ id: 42, type: 'overflow', severity: 'error', message: 'Test' }],
      dismissAlert,
    })
    render(<AlertBanner />)
    fireEvent.click(screen.getByLabelText('Dismiss'))
    expect(dismissAlert).toHaveBeenCalledWith(42)
  })

  it('shows error severity with red styling', () => {
    useDriverStore.__setState({
      alerts: [{ id: 1, type: 'overflow', severity: 'error', message: 'Error alert' }],
    })
    render(<AlertBanner />)
    const banner = screen.getByRole('alert')
    expect(banner.className).toContain('bg-red-600')
  })

  it('shows warning severity with yellow styling', () => {
    useDriverStore.__setState({
      alerts: [{ id: 1, type: 'reroute', severity: 'warning', message: 'Warning alert' }],
    })
    render(<AlertBanner />)
    const banner = screen.getByRole('alert')
    expect(banner.className).toContain('bg-yellow-500')
  })
})

describe('RouteProgress', () => {
  beforeEach(() => useDriverStore.__setState({ allStops: [], stopsCompleted: 0 }))

  it('renders nothing when total is 0', () => {
    const { container } = render(<RouteProgress />)
    expect(container.firstChild).toBeNull()
  })

  it('shows stop count', () => {
    useDriverStore.__setState({
      allStops: [
        { node_id: 'B1', node_type: 'bin' },
        { node_id: 'B2', node_type: 'bin' },
      ],
      stopsCompleted: 1,
    })
    render(<RouteProgress />)
    expect(screen.getByText('Stop 2 of 3')).toBeInTheDocument()
  })

  it('progress bar width reflects completion percentage', () => {
    useDriverStore.__setState({
      allStops: [{ node_id: 'B1', node_type: 'bin' }],
      stopsCompleted: 1,
    })
    render(<RouteProgress />)
    const bar = document.querySelector('[style*="width"]')
    expect(bar.style.width).toBe('50%')
  })
})

describe('ActionButton', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset the singleton offline queue so tests don't bleed into each other
    offlineQueue._queue = []
    useDriverStore.__setState(resetStore())
  })

  it('renders nothing when currentStop is null', () => {
    useDriverStore.__setState({ currentStop: null })
    const { container } = render(<ActionButton />)
    expect(container.firstChild).toBeNull()
  })

  it('shows COLLECTED label for bin stop', () => {
    useDriverStore.__setState({
      currentStop: { node_id: 'B1', node_type: 'bin', fill_collected_liters: 80 },
    })
    render(<ActionButton />)
    expect(screen.getByRole('button', { name: 'COLLECTED' })).toBeInTheDocument()
  })

  it('shows DUMP COMPLETE label for dump_yard stop', () => {
    useDriverStore.__setState({
      currentStop: { node_id: 'Y1', node_type: 'dump_yard', fill_collected_liters: 0 },
    })
    render(<ActionButton />)
    expect(screen.getByRole('button', { name: 'DUMP COMPLETE' })).toBeInTheDocument()
  })

  it('calls advanceStop optimistically on tap', async () => {
    const advanceStop = vi.fn()
    useDriverStore.__setState({
      currentStop: { node_id: 'B1', node_type: 'bin', fill_collected_liters: 100 },
      advanceStop,
    })
    render(<ActionButton />)
    await act(async () => {
      fireEvent.pointerDown(screen.getByRole('button'))
    })
    expect(advanceStop).toHaveBeenCalledWith(100)
  })

  it('calls confirmCollection API for bin stop when online', async () => {
    useDriverStore.__setState({
      truckId: 'T1',
      currentStop: { node_id: 'B1', node_type: 'bin', fill_collected_liters: 80 },
      advanceStop: vi.fn(),
      isOnline: true,
    })
    render(<ActionButton />)
    await act(async () => {
      fireEvent.pointerDown(screen.getByRole('button'))
    })
    expect(api.confirmCollection).toHaveBeenCalledWith('T1', 'B1', 80)
  })

  it('enqueues action offline instead of calling API', async () => {
    const { offlineQueue } = await import('../utils/offlineQueue.js')
    const enqueueSpy = vi.spyOn(offlineQueue, 'enqueue')
    useDriverStore.__setState({
      truckId: 'T1',
      currentStop: { node_id: 'B1', node_type: 'bin', fill_collected_liters: 80 },
      advanceStop: vi.fn(),
      isOnline: false,
    })
    render(<ActionButton />)
    await act(async () => {
      fireEvent.pointerDown(screen.getByRole('button'))
    })
    expect(api.confirmCollection).not.toHaveBeenCalled()
    expect(enqueueSpy).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'collect', truckId: 'T1', nodeId: 'B1' })
    )
    enqueueSpy.mockRestore()
  })

  it('shows sync error message on API failure', async () => {
    api.confirmCollection.mockRejectedValueOnce(new Error('network'))
    useDriverStore.__setState({
      truckId: 'T1',
      currentStop: { node_id: 'B1', node_type: 'bin', fill_collected_liters: 0 },
      advanceStop: vi.fn(),
      isOnline: true,
    })
    render(<ActionButton />)
    await act(async () => {
      fireEvent.pointerDown(screen.getByRole('button'))
    })
    expect(screen.getByText(/Sync failed/)).toBeInTheDocument()
  })
})
