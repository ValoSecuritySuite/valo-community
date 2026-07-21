export const ALL_NAV_SECTIONS = [
  {
    id: 'demo',
    title: 'Experience',
    items: [{ to: '/demo', label: 'Guided Demo', icon: '▶' }],
  },
  {
    id: 'executive',
    title: 'Executive',
    enterpriseOnly: true,
    items: [
      { to: '/executive', label: 'Dashboard', icon: '★' },
      { to: '/reports', label: 'Reports', icon: '☰' },
    ],
  },
  {
    id: 'operate',
    title: 'Operate',
    items: [
      { to: '/', label: 'Overview', icon: '⌖', end: true },
      { to: '/firewall', label: 'AI Firewall', icon: '◆' },
      { to: '/playground', label: 'Playground', icon: '▶' },
    ],
  },
  {
    id: 'author',
    title: 'Author',
    items: [
      { to: '/policies', label: 'Policies', icon: '§' },
      { to: '/rules', label: 'Rules', icon: '≡' },
    ],
  },
  {
    id: 'investigate',
    title: 'Investigate',
    items: [
      { to: '/analysis', label: 'Analysis', icon: '○' },
      {
        to: '/ingestion',
        label: 'Ingestion',
        icon: '⤓',
        enterpriseOnly: true,
      },
    ],
  },
  {
    id: 'learn',
    title: 'Learn',
    enterpriseOnly: true,
    items: [
      { to: '/outcomes', label: 'Outcomes', icon: '◉' },
      { to: '/learning', label: 'Proposals', icon: '⚡' },
    ],
  },
  {
    id: 'configure',
    title: 'Configure',
    items: [{ to: '/settings', label: 'Settings', icon: '⚙' }],
  },
]

/** All nav sections; enterprise items stay visible in Community with badges. */
export function navSectionsForEdition() {
  return ALL_NAV_SECTIONS
}
