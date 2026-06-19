import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'

const US_CENTER = [39.5, -98.35]

// GeoJSON gives [lon, lat]; Leaflet wants [lat, lon].
const toLatLng = (coords) => coords.map(([lon, lat]) => [lat, lon])

const stopIcon = (n) =>
  L.divIcon({ className: '', html: `<div class="pin pin-stop">${n}</div>`, iconSize: [30, 30], iconAnchor: [15, 15] })

const odIcon = (kind) =>
  L.divIcon({ className: '', html: `<div class="pin pin-od ${kind}"></div>`, iconSize: [18, 18], iconAnchor: [9, 9] })

function FitBounds({ positions }) {
  const map = useMap()
  useEffect(() => {
    if (positions && positions.length) map.fitBounds(positions, { padding: [60, 60] })
  }, [positions, map])
  return null
}

const fmt = (n, d = 0) =>
  Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })

export default function App() {
  const [start, setStart] = useState('Wichita, KS')
  const [finish, setFinish] = useState('St. Louis, MO')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [data, setData] = useState(null)

  const plan = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/route/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start, finish }),
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.detail || body.start || body.finish || 'Request failed')
      setData(body)
    } catch (err) {
      setError(String(err.message || err))
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  const line = data ? toLatLng(data.route_geojson.coordinates) : null

  return (
    <div className="app">
      <aside className="panel">
        <div className="brand">
          <h1>DIS<span>PATCH</span></h1>
          <p>Fuel-optimal route planner · 500mi range · 10 mpg</p>
        </div>

        <form onSubmit={plan}>
          <div className="field">
            <label><span className="dot start" /> Origin</label>
            <input value={start} onChange={(e) => setStart(e.target.value)} placeholder="City, ST" />
          </div>
          <div className="field">
            <label><span className="dot finish" /> Destination</label>
            <input value={finish} onChange={(e) => setFinish(e.target.value)} placeholder="City, ST" />
          </div>
          <button className="go" type="submit" disabled={loading}>
            {loading ? 'PLOTTING ROUTE…' : 'PLAN CHEAPEST FUEL'}
          </button>
        </form>

        {error && <div className="error">⚠ {error}</div>}

        {data && (
          <>
            <div className="kpis">
              <div className="kpi">
                <div className="k">Distance</div>
                <div className="v">{fmt(data.total_distance_miles)}<small>mi</small></div>
              </div>
              <div className="kpi">
                <div className="k">Drive time</div>
                <div className="v">{fmt(data.estimated_duration_hours, 1)}<small>hr</small></div>
              </div>
              <div className="kpi">
                <div className="k">Fuel</div>
                <div className="v">{fmt(data.total_gallons, 1)}<small>gal</small></div>
              </div>
              <div className="kpi cost">
                <div className="k">Total cost</div>
                <div className="v">${fmt(data.total_fuel_cost, 2)}</div>
              </div>
            </div>

            <div className="stops">
              <h2>{data.fuel_stops.length} fuel stop{data.fuel_stops.length === 1 ? '' : 's'}</h2>
              {data.fuel_stops.map((s) => (
                <div className="stop" key={s.stop_number}>
                  <div className="badge">{s.stop_number}</div>
                  <div>
                    <div className="name">
                      {s.station ? s.station.name : `${s.state} · national avg`}
                    </div>
                    <div className="meta">
                      {s.station ? `${s.station.city}, ${s.state}` : s.state} ·
                      {' '}{fmt(s.distance_from_start_miles)}mi in · {fmt(s.gallons_purchased, 1)} gal
                    </div>
                  </div>
                  <div className="price">
                    <div className="pg">${fmt(s.price_per_gallon, 2)}</div>
                    <div className="seg">${fmt(s.segment_cost, 2)}</div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {!data && !error && (
          <div className="empty">
            Enter two US locations and hit <b>plan</b>. The planner makes a single
            routing call, then greedily refuels at the <b>cheapest station reachable
            within range</b> — so price, not a fixed mileage, decides every stop.
          </div>
        )}
      </aside>

      <div className="map-wrap">
        {loading && <div className="overlay-loading"><div className="spinner" /></div>}
        <MapContainer center={US_CENTER} zoom={4} zoomControl={false} scrollWheelZoom>
          <TileLayer
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            attribution='&copy; OpenStreetMap &copy; CARTO'
          />
          {line && (
            <>
              <Polyline positions={line} pathOptions={{ color: '#ffae3b', weight: 4, opacity: 0.9 }} />
              <FitBounds positions={line} />
              <Marker position={[data.origin.lat, data.origin.lon]} icon={odIcon('start')}>
                <Popup><b>Origin</b><br />{data.origin.display_name}</Popup>
              </Marker>
              <Marker position={[data.destination.lat, data.destination.lon]} icon={odIcon('finish')}>
                <Popup><b>Destination</b><br />{data.destination.display_name}</Popup>
              </Marker>
              {data.fuel_stops
                .filter((s) => s.stop_number > 1 || data.fuel_stops.length === 1)
                .map((s) => (
                  <Marker key={s.stop_number} position={[s.lat, s.lon]} icon={stopIcon(s.stop_number)}>
                    <Popup>
                      <b>{s.station ? s.station.name : `${s.state} (national avg)`}</b><br />
                      {s.station ? `${s.station.city}, ${s.state}` : s.state}<br />
                      ${fmt(s.price_per_gallon, 2)}/gal · {fmt(s.gallons_purchased, 1)} gal<br />
                      segment ${fmt(s.segment_cost, 2)}
                    </Popup>
                  </Marker>
                ))}
            </>
          )}
        </MapContainer>
      </div>
    </div>
  )
}
