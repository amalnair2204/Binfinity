'use client'
import { MapContainer, TileLayer } from 'react-leaflet'
import BinLayer      from './BinLayer'
import RouteLayer    from './RouteLayer'
import TruckLayer    from './TruckLayer'
import ZoneLayer     from './ZoneLayer'
import HeatmapLayer  from './HeatmapLayer'
import FlyController from './FlyController'
import MapControls   from './MapControls'
import MapLegend     from './MapLegend'
import BinCard       from '../cards/BinCard'

const LAT  = parseFloat(process.env.NEXT_PUBLIC_CITY_LAT  || '51.5074')
const LNG  = parseFloat(process.env.NEXT_PUBLIC_CITY_LNG  || '-0.1278')
const ZOOM = parseFloat(process.env.NEXT_PUBLIC_CITY_ZOOM || '12')

export default function LeafletMap() {
  return (
    <div className="relative w-full h-full">
      <MapContainer
        center={[LAT, LNG]}
        zoom={ZOOM}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
        attributionControl
        zoomControl
      >
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          maxZoom={19}
        />
        <FlyController />
        <ZoneLayer />
        <HeatmapLayer />
        <RouteLayer />
        <BinLayer />
        <TruckLayer />
        <BinCard />
      </MapContainer>
      <MapControls />
      <MapLegend />
    </div>
  )
}
