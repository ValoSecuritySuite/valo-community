export const ALL_NAV_SECTIONS = [
  {
    id: 'executive',
    title: 'Executive',
    enterpriseOnly: true,
    items: [
      { to: '/executive', label: 'Dashboard', icon: '\u2605' },
      { to: '/reports', label: 'Reports', icon: '\u2630' },
    ],
  },
  {
    id: 'operate',
    title: 'Operate',
    items: [
      { to: '/', label: 'Overview', icon: '\u2316', end: true },
      { to: '/firewall', label: 'AI Firewall', icon: '\u25C6' },
      { to: '/playground', label: 'Playground', icon: '\u25B6' },
    ],
  },
  {
    id: 'author',
    title: 'Author',
    items: [
      { to: '/policies', label: 'Policies', icon: '\u00A7' },
      { to: '/rules', label: 'Rules', icon: '\u2261' },
    ],
  },
  {
    id: 'investigate',
    title: 'Investigate',
    items: [
      { to: '/analysis', label: 'Analysis', icon: '\u25CB' },
      {
        to: '/ingestion',
        label: 'Ingestion',
        icon: '\u2913',
        enterpriseOnly: true,
      },
    ],
  },
  {
    id: 'learn',
    title: 'Learn',
    enterpriseOnly: true,
    items: [
      { to: '/outcomes', label: 'Outcomes', icon: '\u25C9' },
      { to: '/learning', label: 'Proposals', icon: '\u26A1' },
    ],
  },
  {
    id: 'configure',
    title: 'Configure',
    items: [{ to: '/settings', label: 'Settings', icon: '\u2699' }],
  },
]

/** All nav sections; enterprise items stay visible in Community with badges. */
export function navSectionsForEdition() {
  return ALL_NAV_SECTIONS
}
