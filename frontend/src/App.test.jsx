import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

// ── fixtures ────────────────────────────────────────────────────────────────

const MOCK_ROUTE = {
  start: 'Austin, TX',
  finish: 'Seattle, WA',
  origin: { lat: 30.2672, lon: -97.7431, display_name: 'Austin, TX, USA' },
  destination: { lat: 47.6062, lon: -122.3321, display_name: 'Seattle, WA, USA' },
  total_distance_miles: 900,
  estimated_duration_hours: 13.5,
  total_gallons: 90,
  total_fuel_cost: 270,
  fuel_stops: [
    {
      stop_number: 1,
      state: 'OR',
      lat: 44.0,
      lon: -120.5,
      distance_from_start_miles: 450,
      miles_covered: 450,
      gallons_purchased: 45,
      price_per_gallon: 3.0,
      segment_cost: 135,
      station: { name: 'OR TRUCKSTOP', city: 'Bend' },
    },
    {
      stop_number: 2,
      state: 'WA',
      lat: 47.6,
      lon: -122.3,
      distance_from_start_miles: 900,
      miles_covered: 450,
      gallons_purchased: 45,
      price_per_gallon: 3.0,
      segment_cost: 135,
      station: { name: 'WA TRUCKSTOP', city: 'Seattle' },
    },
  ],
  route_geojson: {
    type: 'LineString',
    coordinates: [[-97.7431, 30.2672], [-122.3321, 47.6062]],
  },
}

// ── helpers ─────────────────────────────────────────────────────────────────

function mockFetch(body, ok = true, statusCode = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status: statusCode,
    json: async () => body,
  })
}

// ── suite ────────────────────────────────────────────────────────────────────

describe('App – route planner', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch(MOCK_ROUTE))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the origin and destination inputs with default values', () => {
    render(<App />)
    expect(screen.getByDisplayValue('Wichita, KS')).toBeInTheDocument()
    expect(screen.getByDisplayValue('St. Louis, MO')).toBeInTheDocument()
  })

  it('renders the plan button', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: /plan cheapest fuel/i })).toBeInTheDocument()
  })

  it('shows loading state while fetching', async () => {
    // Delay the fetch so we can catch the intermediate loading state
    const slowFetch = vi.fn().mockReturnValue(
      new Promise((resolve) =>
        setTimeout(() => resolve({ ok: true, json: async () => MOCK_ROUTE }), 200)
      )
    )
    vi.stubGlobal('fetch', slowFetch)
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /plan cheapest fuel/i }))
    expect(await screen.findByText(/plotting route/i)).toBeInTheDocument()
  })

  it('calls POST /api/route/ with start and finish after form submit', async () => {
    const user = userEvent.setup()
    render(<App />)

    const originInput = screen.getByDisplayValue('Wichita, KS')
    await user.clear(originInput)
    await user.type(originInput, 'Austin, TX')

    const destInput = screen.getByDisplayValue('St. Louis, MO')
    await user.clear(destInput)
    await user.type(destInput, 'Seattle, WA')

    await user.click(screen.getByRole('button', { name: /plan cheapest fuel/i }))

    await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    const [url, options] = fetch.mock.calls[0]
    expect(url).toBe('/api/route/')
    expect(options.method).toBe('POST')
    const body = JSON.parse(options.body)
    expect(body.start).toBe('Austin, TX')
    expect(body.finish).toBe('Seattle, WA')
  })

  it('displays KPI values after a successful route response', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /plan cheapest fuel/i }))

    await waitFor(() => expect(screen.getByText('900')).toBeInTheDocument())
    expect(screen.getByText('$270.00')).toBeInTheDocument()
    expect(screen.getByText(/2 fuel stop/i)).toBeInTheDocument()
  })

  it('displays each fuel stop with name, price, and segment cost', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /plan cheapest fuel/i }))

    await waitFor(() => screen.getByText('OR TRUCKSTOP'))
    expect(screen.getByText('WA TRUCKSTOP')).toBeInTheDocument()
    const prices = screen.getAllByText('$3.00')
    expect(prices.length).toBe(2)
  })

  it('shows an error message when the API returns a non-OK response', async () => {
    vi.stubGlobal('fetch', mockFetch({ detail: 'Geocoding failed' }, false, 400))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /plan cheapest fuel/i }))

    await waitFor(() => expect(screen.getByText(/geocoding failed/i)).toBeInTheDocument())
    expect(screen.queryByText(/fuel stop/i)).not.toBeInTheDocument()
  })

  it('shows an error when fetch itself throws (network failure)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')))
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /plan cheapest fuel/i }))

    await waitFor(() => expect(screen.getByText(/network error/i)).toBeInTheDocument())
  })

  it('re-enables the button after a response', async () => {
    render(<App />)
    const btn = screen.getByRole('button', { name: /plan cheapest fuel/i })
    fireEvent.click(btn)
    await waitFor(() => expect(btn).not.toBeDisabled())
  })
})
