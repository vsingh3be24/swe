import { Navigate, Route, Routes } from 'react-router-dom'
import NavBar from './components/NavBar'
import ProtectedRoute from './components/ProtectedRoute'
import { useAuth } from './auth/AuthContext'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import SubmitPage from './pages/student/SubmitPage'
import ResultPage from './pages/student/ResultPage'
import NoticesPage from './pages/student/NoticesPage'
import AlertsPage from './pages/student/AlertsPage'
import QueuePage from './pages/reviewer/QueuePage'
import CasePage from './pages/reviewer/CasePage'
import BenchmarkPage from './pages/reviewer/BenchmarkPage'
import SourcesPage from './pages/admin/SourcesPage'
import PublishPage from './pages/issuer/PublishPage'

// The landing route sends each role to its natural home screen.
function Home() {
  const { user } = useAuth()
  if (!user) return <Navigate to="/login" replace />
  switch (user.role) {
    case 'reviewer':
      return <Navigate to="/reviewer/queue" replace />
    case 'admin':
      return <Navigate to="/admin/sources" replace />
    case 'issuer':
      return <Navigate to="/issuer/publish" replace />
    default:
      return <Navigate to="/submit" replace />
  }
}

export default function App() {
  return (
    <div className="app">
      <NavBar />
      <main className="content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          {/* Student */}
          <Route
            path="/submit"
            element={
              <ProtectedRoute roles={['student']}>
                <SubmitPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/result/:id"
            element={
              <ProtectedRoute>
                <ResultPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/notices"
            element={
              <ProtectedRoute>
                <NoticesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/alerts"
            element={
              <ProtectedRoute roles={['student']}>
                <AlertsPage />
              </ProtectedRoute>
            }
          />

          {/* Reviewer */}
          <Route
            path="/reviewer/queue"
            element={
              <ProtectedRoute roles={['reviewer', 'admin']}>
                <QueuePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/reviewer/case/:id"
            element={
              <ProtectedRoute roles={['reviewer', 'admin']}>
                <CasePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/reviewer/benchmark"
            element={
              <ProtectedRoute roles={['reviewer', 'admin']}>
                <BenchmarkPage />
              </ProtectedRoute>
            }
          />

          {/* Admin */}
          <Route
            path="/admin/sources"
            element={
              <ProtectedRoute roles={['admin']}>
                <SourcesPage />
              </ProtectedRoute>
            }
          />

          {/* Issuer */}
          <Route
            path="/issuer/publish"
            element={
              <ProtectedRoute roles={['issuer']}>
                <PublishPage />
              </ProtectedRoute>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
