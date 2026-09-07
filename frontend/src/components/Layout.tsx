import { NavLink } from 'react-router-dom'
import type { ReactNode } from 'react'

interface LayoutProps {
  children: ReactNode
}

const navItems = [
  { path: '/', label: 'داشبورد', labelEn: 'Dashboard', icon: '📊' },
  { path: '/location', label: 'مکان', labelEn: 'Location', icon: '📍' },
  { path: '/vegetation', label: 'پوشش گیاهی', labelEn: 'Vegetation', icon: '🌿' },
  { path: '/climate', label: 'اقلیم', labelEn: 'Climate', icon: '🌤️' },
  { path: '/water', label: 'آب', labelEn: 'Water', icon: '💧' },
  { path: '/soil', label: 'خاک', labelEn: 'Soil', icon: '🌍' },
  { path: '/landcover', label: 'پوشش ارضی', labelEn: 'Land Cover', icon: '🗺️' },
  { path: '/historical', label: 'تاریخی', labelEn: 'Historical', icon: '📈' },
  { path: '/reports', label: 'گزارش‌ها', labelEn: 'Reports', icon: '📋' },
  { path: '/settings', label: 'تنظیمات', labelEn: 'Settings', icon: '⚙️' },
]

export default function Layout({ children }: LayoutProps) {
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
        <nav className="sidebar">
          <ul className="nav-list">
            {navItems.map((item) => (
              <li key={item.path}>
                <NavLink
                  to={item.path}
                  className={({ isActive }) =>
                    `nav-link ${isActive ? 'active' : ''}`
                  }
                  end={item.path === '/'}
                >
                  <span className="nav-icon">{item.icon}</span>
                  <div className="nav-text">
                    <span className="nav-label-fa">{item.label}</span>
                    <span className="nav-label-en">{item.labelEn}</span>
                  </div>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <main className="content">
          {children}
        </main>
      </div>
    </div>
  )
}
