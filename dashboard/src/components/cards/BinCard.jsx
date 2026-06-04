'use client'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMap } from 'react-leaflet'
import L from 'leaflet'
import useDashboardStore from '../../store/dashboardStore'
import { ingestionApi } from '../../lib/apiClient'
import { fillColor } from '../../lib/colorScale'
import FillSparkline from '../charts/FillSparkline'

function priorityLevel(hours) {
  if (hours == null) return null
  if (hours < 1)  return { stars: 3, label: 'CRITICAL', color: '#ff3355' }
  if (hours < 2)  return { stars: 2, label: 'HIGH',     color: '#ff6600' }
  if (hours < 4)  return { stars: 1, label: 'MEDIUM',   color: '#ffaa00' }
  return null
}

function fmtHours(h) {
  if (h < 0.1)  return '<6m'
  if (h < 1)    return `${Math.round(h * 60)}m`
  return `${h.toFixed(1)}h`
}

const S = {
  root:  { background: 'rgba(8,12,16,0.97)', border: '1px solid #1a2535', borderRadius: 6, width: 260, overflow: 'hidden', fontFamily: 'monospace', fontSize: 11 },
  row:   { padding: '5px 10px', borderBottom: '1px solid #1a2535' },
  label: { color: '#4a6280', fontSize: 10 },
  val:   { color: '#c8d8e8' },
  btn:   { flex: 1, padding: '4px 0', fontSize: 10, borderRadius: 3, cursor: 'pointer', fontFamily: 'monospace', border: '1px solid #1a2535', background: 'rgba(13,21,32,0.9)', color: '#4a6280' },
}

function PopupContent({ props, mlPred, history, historyLoading, onClose, onFlag }) {
  const pct   = props.fill_pct ?? 0
  const color = fillColor(pct)
  const fillL = props.capacity_liters ? (pct / 100 * props.capacity_liters).toFixed(1) : null
  const pri   = mlPred ? priorityLevel(mlPred.hours_until_critical) : null
  const statusColor = props.status === 'operational' ? '#00ff88'
    : props.status === 'faulted' ? '#ff3355' : '#ffaa00'

  return (
    <div style={S.root}>
      <div style={{ ...S.row, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#00d4ff', fontWeight: 'bold', fontSize: 12 }}>{props.bin_id}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: statusColor, fontSize: 10 }}>
            ● {(props.status ?? 'unknown').toUpperCase()}
          </span>
          <button onClick={onClose} style={{ color: '#4a6280', background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, lineHeight: 1 }}>✕</button>
        </div>
      </div>

      <div style={{ ...S.row, ...S.label }}>
        Zone: <span style={S.val}>{props.zone_id ?? '—'}</span>
        {props.sector_id && <> / Sector: <span style={S.val}>{props.sector_id}</span></>}
      </div>

      <div style={S.row}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={S.label}>Fill Level</span>
          <span style={{ color, fontWeight: 'bold' }}>{pct.toFixed(1)}%</span>
        </div>
        <div style={{ height: 6, background: '#1a2535', borderRadius: 3 }}>
          <div style={{ height: '100%', width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 3 }} />
        </div>
        {fillL && (
          <div style={{ ...S.label, marginTop: 3 }}>
            {fillL}L / {props.capacity_liters}L
          </div>
        )}
      </div>

      {mlPred && (
        <div style={S.row}>
          <div style={{ color: '#ffaa00' }}>⏱ ~{fmtHours(mlPred.hours_until_critical)} until critical</div>
          {mlPred.model_name && (
            <div style={{ ...S.label, marginTop: 2 }}>
              Model: <span style={S.val}>{mlPred.model_name}</span>
              {mlPred.confidence != null && (
                <> &nbsp; Confidence: <span style={S.val}>{(mlPred.confidence * 100).toFixed(0)}%</span></>
              )}
            </div>
          )}
        </div>
      )}

      <div style={S.row}>
        <div style={{ ...S.label, marginBottom: 3 }}>48h Fill History</div>
        {historyLoading ? (
          <div style={{ height: 40, background: '#0d1520', borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={S.label}>LOADING...</span>
          </div>
        ) : history.length > 1 ? (
          <FillSparkline data={history} height={40} />
        ) : (
          <div style={{ height: 40, background: '#0d1520', borderRadius: 3, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={S.label}>NO HISTORY</span>
          </div>
        )}
      </div>

      {(pri || props.road_type || props.battery_mv != null) && (
        <div style={{ ...S.row, ...S.label }}>
          {pri && (
            <div style={{ color: pri.color }}>
              Priority: {'★'.repeat(pri.stars)}{'☆'.repeat(3 - pri.stars)} {pri.label}
            </div>
          )}
          {props.road_type && (
            <div style={{ marginTop: 2 }}>
              Road: <span style={{ color: props.road_type.toLowerCase().includes('narrow') ? '#ffaa00' : '#c8d8e8' }}>
                {props.road_type.toUpperCase()}
                {props.road_type.toLowerCase().includes('narrow') && ' ⚠'}
              </span>
            </div>
          )}
          {props.battery_mv != null && (
            <div style={{ marginTop: 2 }}>
              Battery: <span style={{ color: props.battery_mv > 3500 ? '#00ff88' : '#ffaa00' }}>
                {props.battery_mv}mV {props.battery_mv > 3500 ? '✓' : '!'}
              </span>
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 6, padding: '6px 10px' }}>
        <button
          onClick={onFlag}
          style={{
            ...S.btn,
            background:  props.flagged ? 'rgba(255,170,0,0.15)' : 'rgba(13,21,32,0.9)',
            borderColor: props.flagged ? '#ffaa00' : '#1a2535',
            color:       props.flagged ? '#ffaa00' : '#4a6280',
          }}
        >
          {props.flagged ? '⚑ UNFLAG' : '⚐ FLAG'}
        </button>
        <button onClick={onClose} style={S.btn}>CLOSE</button>
      </div>
    </div>
  )
}

export default function BinCard() {
  const map              = useMap()
  const selectedBinId    = useDashboardStore((s) => s.selectedBinId)
  const setSelectedBinId = useDashboardStore((s) => s.setSelectedBinId)
  const bins             = useDashboardStore((s) => s.bins)
  const setBins          = useDashboardStore((s) => s.setBins)
  const mlPredictions    = useDashboardStore((s) => s.mlPredictions)

  const [history, setHistory]               = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [container, setContainer]           = useState(null)
  const popupRef = useRef(null)

  const feature = bins?.features?.find((f) => f.properties.bin_id === selectedBinId)
  const props   = feature?.properties ?? {}
  const mlPred  = mlPredictions.find((p) => p.bin_id === selectedBinId) ?? null

  useEffect(() => {
    if (!map || !selectedBinId || !feature) {
      if (popupRef.current) {
        map?.closePopup(popupRef.current)
        popupRef.current = null
      }
      setContainer(null)
      return
    }

    const [lng, lat] = feature.geometry.coordinates
    const el = document.createElement('div')

    const popup = L.popup({
      closeButton:  false,
      closeOnClick: false,
      maxWidth:     270,
      className:    'binfinity-popup',
      offset:       [0, -4],
    })
      .setLatLng([lat, lng])
      .setContent(el)
      .openOn(map)

    popupRef.current = popup
    setContainer(el)

    return () => {
      map.closePopup(popup)
      popupRef.current = null
    }
  }, [map, selectedBinId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedBinId) { setHistory([]); return }
    setHistoryLoading(true)
    setHistory([])
    ingestionApi.binHistory(selectedBinId, 48)
      .then((rows) =>
        setHistory(rows.map((r) => ({ t: r.recorded_at ?? r.timestamp, v: r.fill_pct ?? 0 })))
      )
      .catch(() => {})
      .finally(() => setHistoryLoading(false))
  }, [selectedBinId])

  const handleFlag = () => {
    if (!selectedBinId || !bins) return
    setBins({
      ...bins,
      features: bins.features.map((f) =>
        f.properties.bin_id === selectedBinId
          ? { ...f, properties: { ...f.properties, flagged: !f.properties.flagged } }
          : f,
      ),
    })
  }

  if (!container || !feature) return null

  return createPortal(
    <PopupContent
      props={props}
      mlPred={mlPred}
      history={history}
      historyLoading={historyLoading}
      onClose={() => setSelectedBinId(null)}
      onFlag={handleFlag}
    />,
    container,
  )
}
