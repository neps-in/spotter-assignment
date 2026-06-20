import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import VerifyPanel from './VerifyPanel'

// ── fixtures ─────────────────────────────────────────────────────────────────

const PASS_REPORT = {
  run_id: 'abc12345',
  generated_at: '2026-06-20T10:00:00.000Z',
  route_under_test: { start: 'Austin, TX', finish: 'Seattle, WA' },
  summary: { total: 5, passed: 5, failed: 0, all_passed: true },
  tests: [
    { id: 1, name: 'Response contract', passed: true, details: '200 OK with all 6 contract fields.', metrics: { distance_miles: 900, fuel_stops: 2 } },
    { id: 2, name: 'Range constraint (<=450 mi/leg)', passed: true, details: 'All 2 legs <= 450 mi.', metrics: { longest_leg_miles: 450, safe_range: 450 } },
    { id: 3, name: 'Cost math consistency', passed: true, details: 'gallons=90; costs sum to $270.', metrics: { total_gallons: 90, total_fuel_cost: 270 } },
    { id: 4, name: 'GeoJSON validity (USA LineString)', passed: true, details: '50 coordinates, all within the contiguous-USA box.', metrics: { points: 50 } },
    { id: 5, name: 'Identical locations rejected', passed: true, details: 'Correctly rejected with HTTP 400.', metrics: { status: 400 } },
  ],
}

const PARTIAL_FAIL_REPORT = {
  ...PASS_REPORT,
  summary: { total: 5, passed: 3, failed: 2, all_passed: false },
  tests: [
    ...PASS_REPORT.tests.slice(0, 3),
    { id: 4, name: 'GeoJSON validity (USA LineString)', passed: false, details: '1 coordinate falls outside the USA box.', metrics: { points: 50 } },
    { id: 5, name: 'Identical locations rejected', passed: false, details: 'Expected HTTP 400, got 200.', metrics: { status: 200 } },
  ],
}

function mockFetch(body, ok = true) {
  return vi.fn().mockResolvedValue({ ok, json: async () => body })
}

// ── suite ─────────────────────────────────────────────────────────────────────

describe('VerifyPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('renders the run button and idle instructions on mount', () => {
    render(<VerifyPanel />)
    expect(screen.getByRole('button', { name: /run/i })).toBeInTheDocument()
    // Text is split across <b> element; use the container to check presence
    expect(screen.getByText(/to execute the live verification suite/i)).toBeInTheDocument()
  })

  it('shows a loading spinner while the request is in-flight', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValue(new Promise(() => {})) // never resolves
    )
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))
    expect(await screen.findByText(/running/i)).toBeInTheDocument()
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('calls GET /api/verify/ when run is clicked', async () => {
    vi.stubGlobal('fetch', mockFetch(PASS_REPORT))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/verify/'))
  })

  it('displays 5/5 pass summary and all test names on a full-pass run', async () => {
    vi.stubGlobal('fetch', mockFetch(PASS_REPORT))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))

    await waitFor(() => screen.getByText(/all tests passed/i))
    // score-num span contains the passed count
    expect(document.querySelector('.score-num')).toHaveTextContent('5')
    expect(screen.getByText('Response contract')).toBeInTheDocument()
    expect(screen.getByText('Cost math consistency')).toBeInTheDocument()
    expect(screen.getByText('Identical locations rejected')).toBeInTheDocument()
  })

  it('shows a PASS badge for passing tests', async () => {
    vi.stubGlobal('fetch', mockFetch(PASS_REPORT))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))
    await waitFor(() => screen.getByText(/all tests passed/i))
    const badges = screen.getAllByText('PASS')
    expect(badges.length).toBe(5)
  })

  it('shows FAIL badges and failure summary for a partial-fail run', async () => {
    vi.stubGlobal('fetch', mockFetch(PARTIAL_FAIL_REPORT))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))

    await waitFor(() => screen.getByText(/2 tests failed/i))
    expect(screen.getAllByText('FAIL').length).toBe(2)
    expect(screen.getAllByText('PASS').length).toBe(3)
  })

  it('expands test details and metrics when a test row is clicked', async () => {
    vi.stubGlobal('fetch', mockFetch(PASS_REPORT))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))
    await waitFor(() => screen.getByText('Response contract'))

    // Details and metrics are hidden by default
    expect(screen.queryByText(/200 OK with all/i)).not.toBeInTheDocument()

    // Click the first test-header button (aria-expanded="false")
    const testHeaders = document.querySelectorAll('.test-header')
    fireEvent.click(testHeaders[0])
    expect(await screen.findByText(/200 OK with all/i)).toBeInTheDocument()
    expect(screen.getByText('distance miles')).toBeInTheDocument()
    expect(screen.getByText('900')).toBeInTheDocument()
  })

  it('displays the route under test (start → finish)', async () => {
    vi.stubGlobal('fetch', mockFetch(PASS_REPORT))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))
    await waitFor(() => screen.getByText(/Austin, TX → Seattle, WA/))
  })

  it('shows an error message when /api/verify/ returns non-OK', async () => {
    vi.stubGlobal('fetch', mockFetch({ detail: 'Service unavailable' }, false))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))
    await waitFor(() => screen.getByText(/service unavailable/i))
  })

  it('shows an error when fetch throws a network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Failed to fetch')))
    render(<VerifyPanel />)
    fireEvent.click(screen.getByRole('button', { name: /run/i }))
    await waitFor(() => screen.getByText(/failed to fetch/i))
  })

  it('re-enables the run button after an error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('oops')))
    render(<VerifyPanel />)
    const btn = screen.getByRole('button', { name: /run/i })
    fireEvent.click(btn)
    await waitFor(() => expect(btn).not.toBeDisabled())
  })
})
