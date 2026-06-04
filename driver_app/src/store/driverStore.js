import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Global driver state. Persists only truckId across page refreshes so the
 * driver doesn't have to re-enter it after a browser restart.
 *
 * Route state is always server-authoritative: setRoute() accepts the raw
 * stops array from GET /routing/routes/truck/{id} and derives currentStop /
 * nextStop from the head of the remaining list. advanceStop() optimistically
 * shifts the local list while the server syncs asynchronously.
 */
const useDriverStore = create(
  persist(
    (set, get) => ({
      // ── identity ──────────────────────────────────────────────────────────
      truckId: null,

      // ── route ─────────────────────────────────────────────────────────────
      /** Remaining stops (non-depot) from the server's current route view. */
      allStops: [],
      currentStop: null,
      nextStop: null,
      stopsCompleted: 0,

      // ── truck telemetry ───────────────────────────────────────────────────
      loadLiters: 0,
      capacityLiters: 10_000,
      status: 'unknown',
      position: null,

      // ── shift lifecycle ───────────────────────────────────────────────────
      shiftStarted: false,
      shiftEnded: false,
      binsCollectedToday: 0,
      litersCollectedToday: 0,

      // ── alerts ────────────────────────────────────────────────────────────
      alerts: [],

      // ── connectivity ──────────────────────────────────────────────────────
      isConnected: false,
      isOnline: typeof navigator !== 'undefined' ? navigator.onLine : true,

      // ── actions ───────────────────────────────────────────────────────────

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

      /**
       * Replace the local stop list with fresh data from the backend.
       * allStops receives only non-depot stops; stopsCompleted resets to 0
       * because the server has already removed completed stops from its route.
       */
      setRoute: (stops) => {
        const nonDepot = (stops ?? []).filter((s) => s.node_type !== 'depot')
        set({
          allStops: nonDepot,
          stopsCompleted: 0,
          currentStop: nonDepot[0] ?? null,
          nextStop: nonDepot[1] ?? null,
        })
      },

      /** Optimistically advance past the head stop. Server will confirm on next poll. */
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
      // Only persist the truck ID — route and shift data always re-fetches.
      partialize: (state) => ({ truckId: state.truckId }),
    },
  ),
)

export default useDriverStore
