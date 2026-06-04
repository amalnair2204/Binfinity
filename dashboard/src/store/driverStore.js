import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const useDriverStore = create(
  persist(
    (set, get) => ({
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
      isOnline: typeof navigator !== 'undefined' ? navigator.onLine : true,

      setTruckId: (id) => set({ truckId: id }),

      startShift: () =>
        set({
          shiftStarted: true,
          shiftEnded: false,
          stopsCompleted: 0,
          allStops: [],
          currentStop: null,
          nextStop: null,
          binsCollectedToday: 0,
          litersCollectedToday: 0,
          alerts: [],
        }),

      endShift: () => set({ shiftEnded: true }),

      setRoute: (stops) => {
        const nonDepot = (stops ?? []).filter((s) => s.node_type !== 'depot')
        set({
          allStops: nonDepot,
          stopsCompleted: 0,
          currentStop: nonDepot[0] ?? null,
          nextStop: nonDepot[1] ?? null,
        })
      },

      advanceStop: (liters = 0) =>
        set((state) => {
          const next = state.allStops.slice(1)
          return {
            allStops: next,
            stopsCompleted: state.stopsCompleted + 1,
            currentStop: next[0] ?? null,
            nextStop: next[1] ?? null,
            binsCollectedToday:
              state.binsCollectedToday +
              (state.currentStop?.node_type === 'bin' ? 1 : 0),
            litersCollectedToday: state.litersCollectedToday + (liters ?? 0),
          }
        }),

      setTruckState: ({ loadLiters, capacityLiters, status, position }) =>
        set({
          loadLiters: loadLiters ?? 0,
          capacityLiters: capacityLiters || 10_000,
          status: status ?? 'unknown',
          position: position ?? null,
        }),

      addAlert: (alert) =>
        set((s) => ({ alerts: [alert, ...s.alerts].slice(0, 10) })),

      dismissAlert: (id) =>
        set((s) => ({ alerts: s.alerts.filter((a) => a.id !== id) })),

      setConnected: (v) => set({ isConnected: v }),
      setOnline: (v) => set({ isOnline: v }),
    }),
    {
      name: 'binfinity-driver-store',
      partialize: (state) => ({ truckId: state.truckId }),
    },
  ),
)

export default useDriverStore
