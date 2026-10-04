import { NavLink, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

interface LayoutProps {
  children: ReactNode
}

interface NavChild {
  path: string
  label: string
  labelEn: string
  icon: string
  end?: boolean
}

interface NavEntry {
  path: string
  label: string
  labelEn: string
  icon: string
  end?: boolean
  children?: NavChild[]
}

/**
 * Main navigation (Prompt 1: navigation IA).
 * Domain pages (Vegetation / Water / Soil / Climate / Land Cover / ...)
 * are nested under "Agriculture Analysis" — never top-level items.
 * Route paths are unchanged; only grouping changed.
 */
const navItems: NavEntry[] = [
  { path: '/', label: 'داشبورد', labelEn: 'Dashboard', icon: '📊', end: true },
  { path: '/location', label: 'مکان', labelEn: 'Location', icon: '📍' },
  {
    path: '/agriculture',
    label: 'تحلیل کشاورزی',
    labelEn: 'Agriculture Analysis',
    icon: '🌾',
    children: [
      { path: '/agriculture', label: 'نمای کلی', labelEn: 'Overview', icon: '🧭', end: true },
      { path: '/agriculture/vegetation', label: 'پوشش گیاهی و کانوپی', labelEn: 'Vegetation & Canopy', icon: '🌿' },
      { path: '/agriculture/water', label: 'آب و رطوبت', labelEn: 'Water & Moisture', icon: '💧' },
      { path: '/agriculture/soil', label: 'خاک', labelEn: 'Soil', icon: '🌍' },
      { path: '/agriculture/climate', label: 'اقلیم', labelEn: 'Climate', icon: '🌤️' },
      { path: '/agriculture/thermal', label: 'حرارتی', labelEn: 'Thermal', icon: '🌡️' },
      { path: '/agriculture/land-crop', label: 'پوشش ارضی و زراعی', labelEn: 'Land Cover & Crop', icon: '🗺️' },
      { path: '/agriculture/phenology', label: 'فنولوژی', labelEn: 'Phenology', icon: '📅' },
      { path: '/agriculture/stress-irrigation', label: 'تنش و آبیاری', labelEn: 'Stress & Irrigation', icon: '🚿' },
      { path: '/agriculture/terrain', label: 'توپوگرافی', labelEn: 'Terrain', icon: '⛰️' },
      { path: '/agriculture/history', label: 'تاریخچه', labelEn: 'History', icon: '🕓' },
    ],
  },
  { path: '/historical', label: 'تحلیل تاریخی', labelEn: 'Historical Analysis', icon: '📈' },
  { path: '/reports', label: 'گزارش‌ها', labelEn: 'Reports', icon: '📋' },
  { path: '/settings', label: 'تنظیمات', labelEn: 'Settings', icon: '⚙️' },
]

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()

  return (
    <div className="layout">
      <header className="header">
        <div className="header-title">
          <span className="header-icon">🌾</span>
          <h1>پلتفرم هوش کشاورزی</h1>
          <span className="header-subtitle">Agricultural Intelligence Platform</span>
        </div>
      </header>

      <div className="main-container">
        <nav className="sidebar" aria-label="Main navigation">
          <ul className="nav-list">
            {navItems.map((item) => {
              if (!item.children) {
                return (
                  <li key={item.path}>
                    <NavLink
                      to={item.path}
                      className={({ isActive }) =>
                        `nav-link ${isActive ? 'active' : ''}`
                      }
                      end={item.end ?? item.path === '/'}
                    >
                      <span className="nav-icon">{item.icon}</span>
                      <div className="nav-text">
                        <span className="nav-label-fa">{item.label}</span>
                        <span className="nav-label-en">{item.labelEn}</span>
                      </div>
                    </NavLink>
                  </li>
                )
              }

              const groupActive =
                location.pathname === item.path ||
                location.pathname.startsWith(`${item.path}/`)

              return (
                <li key={item.path} className={`nav-group ${groupActive ? 'nav-group-active' : ''}`}>
                  <NavLink
                    to={item.path}
                    end
                    className={({ isActive }) =>
                      `nav-link nav-group-link ${isActive || groupActive ? 'active' : ''}`
                    }
                  >
                    <span className="nav-icon">{item.icon}</span>
                    <div className="nav-text">
                      <span className="nav-label-fa">{item.label}</span>
                      <span className="nav-label-en">{item.labelEn}</span>
                    </div>
                  </NavLink>
                  <ul className="nav-sublist" aria-label={item.labelEn}>
                    {item.children.map((child) => (
                      <li key={child.path}>
                        <NavLink
                          to={child.path}
                          end={child.end}
                          className={({ isActive }) =>
                            `nav-link nav-sublink ${isActive ? 'active' : ''}`
                          }
                        >
                          <span className="nav-icon">{child.icon}</span>
                          <div className="nav-text">
                            <span className="nav-label-fa">{child.label}</span>
                            <span className="nav-label-en">{child.labelEn}</span>
                          </div>
                        </NavLink>
                      </li>
                    ))}
                  </ul>
                </li>
              )
            })}
          </ul>
        </nav>

        <main className="content">
          {children}
        </main>
      </div>
    </div>
  )
}
