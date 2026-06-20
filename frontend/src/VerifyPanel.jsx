import { useState } from 'react'

const STATUS = {
  idle: 'idle',
  running: 'running',
  done: 'done',
  error: 'error',
}

function MetricPill({ label, value }) {
  return (
    <span className="metric-pill">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value}</span>
    </span>
  )
}

function TestRow({ test }) {
  const [open, setOpen] = useState(false)
  const hasMetrics = test.metrics && Object.keys(test.metrics).length > 0
  return (
    <div className={`test-row ${test.passed ? 'pass' : 'fail'}`}>
      <button className="test-header" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className={`test-badge ${test.passed ? 'pass' : 'fail'}`}>
          {test.passed ? 'PASS' : 'FAIL'}
        </span>
        <span className="test-id">{test.id}</span>
        <span className="test-name">{test.name}</span>
        <span className="chevron">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="test-body">
          <p className="test-details">{test.details}</p>
          {hasMetrics && (
            <div className="test-metrics">
              {Object.entries(test.metrics).map(([k, v]) => (
                <MetricPill key={k} label={k.replace(/_/g, ' ')} value={String(v)} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function VerifyPanel() {
  const [status, setStatus] = useState(STATUS.idle)
  const [report, setReport] = useState(null)
  const [errMsg, setErrMsg] = useState(null)

  const run = async () => {
    setStatus(STATUS.running)
    setReport(null)
    setErrMsg(null)
    try {
      const res = await fetch('/api/verify/')
      const body = await res.json()
      if (!res.ok) throw new Error(body.detail || 'Verification failed')
      setReport(body)
      setStatus(STATUS.done)
    } catch (err) {
      setErrMsg(String(err.message || err))
      setStatus(STATUS.error)
    }
  }

  const summary = report?.summary
  const allPassed = summary?.all_passed

  return (
    <div className="verify-panel">
      <div className="verify-header">
        <div>
          <div className="verify-title">LIVE TEST SUITE</div>
          <div className="verify-subtitle">
            Runs 5 real-world checks against <code>/api/route/</code> using random US cities
          </div>
        </div>
        <button
          className={`run-btn ${status === STATUS.running ? 'running' : ''}`}
          onClick={run}
          disabled={status === STATUS.running}
        >
          {status === STATUS.running ? (
            <><span className="spinner-sm" /> RUNNING…</>
          ) : (
            '▶ RUN'
          )}
        </button>
      </div>

      {status === STATUS.error && (
        <div className="verify-error">⚠ {errMsg}</div>
      )}

      {status === STATUS.idle && (
        <div className="verify-empty">
          Hit <b>▶ RUN</b> to execute the live verification suite.
          Each run picks a fresh pair of random US cities and exercises
          the full API stack — geocoding, routing, and the fuel planner.
        </div>
      )}

      {report && (
        <>
          <div className={`verify-summary ${allPassed ? 'all-pass' : 'has-fail'}`}>
            <div className="summary-score">
              <span className="score-num">{summary.passed}</span>
              <span className="score-sep">/</span>
              <span className="score-total">{summary.total}</span>
            </div>
            <div className="summary-right">
              <div className="summary-label">
                {allPassed ? '✓ All tests passed' : `✗ ${summary.failed} test${summary.failed !== 1 ? 's' : ''} failed`}
              </div>
              <div className="summary-route">
                {report.route_under_test.start} → {report.route_under_test.finish}
              </div>
              <div className="summary-meta">
                run <code>{report.run_id}</code> · {new Date(report.generated_at).toLocaleTimeString()}
              </div>
            </div>
          </div>

          <div className="test-list">
            {report.tests.map((t) => (
              <TestRow key={t.id} test={t} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
