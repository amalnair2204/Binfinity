import { createContext, useContext } from 'react'

export const MapContext = createContext(null)

export function useMap() {
  return useContext(MapContext)
}
