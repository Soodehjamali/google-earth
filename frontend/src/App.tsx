import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Location from './pages/Location'
import Analysis from './pages/Analysis'
import Agriculture from './pages/Agriculture'
import Historical from './pages/Historical'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import AgricultureLayout from './components/agriculture/AgricultureLayout'
import DomainPage from './pages/agriculture/DomainPage'
import PestDiseasePage from './pages/agriculture/PestDiseasePage'

function RedirectPreservingSearch({ to }: { to: string }) {
  const location = useLocation()
  return <Navigate to={{ pathname: to, search: location.search }} replace />
}

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/location" element={<Location />} />
        <Route path="/analysis/:id" element={<Analysis />} />
        <Route path="/vegetation" element={<RedirectPreservingSearch to="/agriculture/vegetation" />} />
        <Route path="/climate" element={<RedirectPreservingSearch to="/agriculture/climate" />} />
        <Route path="/water" element={<RedirectPreservingSearch to="/agriculture/water" />} />
        <Route path="/soil" element={<RedirectPreservingSearch to="/agriculture/soil" />} />
        <Route path="/landcover" element={<RedirectPreservingSearch to="/agriculture/land-crop" />} />
        <Route path="/agriculture" element={<AgricultureLayout />}>
          <Route index element={<Agriculture />} />
          <Route path="vegetation" element={<DomainPage pageKey="vegetation" />} />
          <Route path="phenology" element={<DomainPage pageKey="phenology" />} />
          <Route path="climate" element={<DomainPage pageKey="climate" />} />
          <Route path="water" element={<DomainPage pageKey="water" />} />
          <Route path="soil" element={<DomainPage pageKey="soil" />} />
          <Route path="thermal" element={<DomainPage pageKey="thermal" />} />
          <Route path="terrain" element={<DomainPage pageKey="terrain" />} />
          <Route path="land-crop" element={<DomainPage pageKey="land-crop" />} />
          <Route
            path="stress-irrigation"
            element={<DomainPage pageKey="stress-irrigation" />}
          />
          <Route path="history" element={<DomainPage pageKey="history" />} />
          <Route path="pest-disease" element={<PestDiseasePage />} />
          <Route path="pest-disease-validation" element={<PestDiseasePage />} />
        </Route>
        <Route path="/historical" element={<Historical />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </Layout>
  )
}

export default App
