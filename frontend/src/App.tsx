import { NavLink, Outlet, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { MockBanner } from './components/ui'
import { useEventState } from './hooks/useEventState'
import BriefPage from './pages/BriefPage'
import Landing from './pages/Landing'
import MapDashboard from './pages/MapDashboard'
import PlanPage from './pages/PlanPage'
import ValidationPage from './pages/ValidationPage'

const NAV = [
  { to: 'map', label: 'Map', icon: 'M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z' },
  { to: 'plan', label: 'Plan', icon: 'M12 2a7 7 0 017 7c0 5-7 13-7 13S5 14 5 9a7 7 0 017-7z' },
  { to: 'validation', label: 'Validation', icon: 'M4 20V10M10 20V4M16 20v-8M22 20H2' },
  { to: 'brief', label: 'Brief', icon: 'M6 2h9l5 5v15H6zM14 2v6h6' },
]

function EventLayout() {
  const { eventId } = useParams()
  const { event, day } = useEventState()
  const { search } = useLocation()
  const qs = search || `?day=${day}`
  return (
    <div className="flex h-full flex-col">
      <MockBanner mode={event?.data_mode} />
      <div className="flex min-h-0 flex-1">
        <nav className="flex w-[72px] shrink-0 flex-col items-center gap-1 border-r border-line bg-panel py-3">
          <NavLink to="/" className="mb-3 text-[10px] font-bold uppercase tracking-wider text-red-400" title="Overview">
            OAD
          </NavLink>
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={`/event/${eventId}/${n.to}${qs.replace(/&?zip=[^&]*/, '')}`}
              className={({ isActive }) =>
                `flex w-14 flex-col items-center gap-1 rounded-md py-2 text-[10px] ${
                  isActive ? 'bg-panel-2 text-text' : 'text-muted hover:text-text'
                }`
              }
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
                <path d={n.icon} />
              </svg>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/event/:eventId" element={<EventLayout />}>
        <Route path="map" element={<MapDashboard />} />
        <Route path="plan" element={<PlanPage />} />
        <Route path="validation" element={<ValidationPage />} />
        <Route path="brief" element={<BriefPage />} />
      </Route>
    </Routes>
  )
}
