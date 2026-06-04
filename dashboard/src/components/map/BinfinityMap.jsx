'use client'
import dynamic from 'next/dynamic'

// Leaflet requires window — load client-side only
const LeafletMap = dynamic(() => import('./LeafletMap'), {
  ssr: false,
  loading: () => <div className="absolute inset-0 bg-ops-bg" />,
})

export default function BinfinityMap() {
  return <LeafletMap />
}
