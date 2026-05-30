import { NavLink } from 'react-router-dom'

import { navSectionsForEdition } from '../../lib/navSections.js'

export default function Sidebar({ backendLabel, isCommunity = false }) {
  const sections = navSectionsForEdition()

  return (
    <aside className="app-sidebar" aria-label="Primary navigation">
      <div className="sidebar-brand">
        <div
          className="sidebar-brand-mark"
          role="img"
          aria-label="Valo logo"
        />
        <div>
          <p className="sidebar-brand-eyebrow">Valo</p>
          <h2 className="sidebar-brand-title">
            {isCommunity ? 'Community Edition' : 'AI Firewall Console'}
          </h2>
        </div>
      </div>

      <nav className="sidebar-nav">
        {sections.map((section) => (
          <div key={section.title} className="sidebar-section">
            <p className="sidebar-section-title">
              {section.title}
              {isCommunity && section.enterpriseOnly ? (
                <span className="sidebar-section-badge">Enterprise</span>
              ) : null}
            </p>
            <ul className="sidebar-section-list">
              {section.items.map((item) => {
                const enterpriseLocked = isCommunity && item.enterpriseOnly
                return (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      end={Boolean(item.end)}
                      className={({ isActive }) =>
                        [
                          'sidebar-link',
                          isActive ? 'sidebar-link-active' : '',
                          enterpriseLocked ? 'sidebar-link-enterprise' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')
                      }
                      title={
                        enterpriseLocked
                          ? `${item.label} requires Valo Enterprise (not in Community Edition)`
                          : item.label
                      }
                    >
                      <span className="sidebar-link-icon" aria-hidden="true">
                        {item.icon}
                      </span>
                      <span className="sidebar-link-label">{item.label}</span>
                      {enterpriseLocked ? (
                        <span className="sidebar-link-badge">Enterprise</span>
                      ) : null}
                    </NavLink>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <p className="muted small">{backendLabel || 'Backend status'}</p>
        {isCommunity ? (
          <p className="muted small">Open source Community Edition</p>
        ) : null}
      </div>
    </aside>
  )
}
