import { create } from 'zustand'

const useDashboardStore = create((set) => ({
  // Data
  bins: null,          // GeoJSONFeatureCollection enriched with fill_pct
  zones: null,         // GeoJSONFeatureCollection for zone polygons
  routes: [],          // OptimizedRoute[]
  trucks: [],          // DispatchTruckState[]
  fleetStats: null,    // { total, flagged, overflow_risk, faulted, operational, ... }
  mlPredictions: [],   // PredictionResult[]
  alerts: [],          // DispatchEvent[] — newest first, capped at 100

  // UI state
  selectedBinId: null,   // string | null
  selectedTruckId: null, // string | null
  wsStatus: 'disconnected', // 'connected' | 'disconnected' | 'reconnecting'
  layerVisibility: { bins: true, trucks: true, routes: true, heatmap: false },
  mapFlyTarget: null, // { center: [lng, lat], zoom?: number } | null

  // Actions
  setBins:          (bins)   => set({ bins }),
  setZones:         (zones)  => set({ zones }),
  setRoutes:        (routes) => set({ routes }),
  setTrucks:        (trucks) => set({ trucks }),
  setFleetStats:    (fs)     => set({ fleetStats: fs }),
  setMLPredictions: (preds)  => set({ mlPredictions: preds }),
  setAlerts:        (alerts) => set({ alerts }),
  prependAlert:     (alert)  =>
    set((s) => ({ alerts: [alert, ...s.alerts].slice(0, 100) })),

  setSelectedBinId:   (id) => set({ selectedBinId: id }),
  setSelectedTruckId: (id) => set({ selectedTruckId: id }),
  setWsStatus:        (st) => set({ wsStatus: st }),

  toggleLayer: (name) =>
    set((s) => ({
      layerVisibility: { ...s.layerVisibility, [name]: !s.layerVisibility[name] },
    })),

  setMapFlyTarget: (target) => set({ mapFlyTarget: target }),

  updateTruckPosition: (truckId, lat, lng) =>
    set((s) => ({
      trucks: s.trucks.map((t) =>
        t.truck_id === truckId ? { ...t, position: { lat, lng } } : t,
      ),
    })),

  updateRoutes: (routes) => set({ routes }),

  // Calibration panel
  calibrationVisible: false,
  fleetAccuracy: null,
  worstBins: [],
  retrainJobs: [],
  toggleCalibration: () => set((s) => ({ calibrationVisible: !s.calibrationVisible })),
  setCalibrationData: (data) => set(data),
}))

export default useDashboardStore
