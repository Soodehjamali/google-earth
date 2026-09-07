import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Location from './pages/Location'
import Analysis from './pages/Analysis'
import Vegetation from './pages/Vegetation'
import Climate from './pages/Climate'
import Water from './pages/Water'
import Soil from './pages/Soil'
import LandCover from './pages/LandCover'
import Historical from './pages/Historical'
import Reports from './pages/Reports'
import Settings from './pages/Settings'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/location" element={<Location />} />
        <Route path="/analysis/:id" element={<Analysis />} />
        <Route path="/vegetation" element={<Vegetation />} />
        <Route path="/climate" element={<Climate />} />
        <Route path="/water" element={<Water />} />
        <Route path="/soil" element={<Soil />} />
        <Route path="/landcover" element={<LandCover />} />
        <Route path="/historical" element={<Historical />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </Layout>
  )
}

export default App
