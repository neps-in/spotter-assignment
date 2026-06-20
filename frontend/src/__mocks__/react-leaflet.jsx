// Stub out the entire react-leaflet library so jsdom doesn't need a browser
// canvas or tile networking. Tests focus on data-flow, not map rendering.
import { useEffect } from 'react'

export const MapContainer = ({ children }) => <div data-testid="map">{children}</div>
export const TileLayer = () => null
export const Polyline = () => <div data-testid="polyline" />
export const Marker = ({ children }) => <div data-testid="marker">{children}</div>
export const Popup = ({ children }) => <div data-testid="popup">{children}</div>
export const useMap = () => ({ fitBounds: () => {} })
