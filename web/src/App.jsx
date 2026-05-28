import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { getEditionMeta, isCommunityEdition } from './api/edition.js'
import AppShell from './components/layout/AppShell.jsx'
import AnalysisView from './views/AnalysisView.jsx'
import ExecutiveView from './views/ExecutiveView.jsx'
import FirewallView from './views/FirewallView.jsx'
import IngestionView from './views/IngestionView.jsx'
import LearningView from './views/LearningView.jsx'
import OutcomesView from './views/OutcomesView.jsx'
import OverviewView from './views/OverviewView.jsx'
import PlaygroundView from './views/PlaygroundView.jsx'
import PoliciesView from './views/PoliciesView.jsx'
import ReportsView from './views/ReportsView.jsx'
import RulesView from './views/RulesView.jsx'
import SettingsView from './views/SettingsView.jsx'

function EnterpriseOnly({ children, isCommunity }) {
  if (isCommunity) {
    return <Navigate to="/" replace />
  }
  return children
}

export default function App() {
  const editionQuery = useQuery({
    queryKey: ['meta', 'edition'],
    queryFn: getEditionMeta,
    staleTime: 60_000,
  })
  const isCommunity = isCommunityEdition(editionQuery.data)

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewView />} />
        <Route
          path="executive"
          element={
            <EnterpriseOnly isCommunity={isCommunity}>
              <ExecutiveView />
            </EnterpriseOnly>
          }
        />
        <Route path="firewall" element={<FirewallView />} />
        <Route path="playground" element={<PlaygroundView />} />
        <Route path="policies" element={<PoliciesView />} />
        <Route path="rules" element={<RulesView />} />
        <Route path="analysis" element={<AnalysisView />} />
        <Route
          path="ingestion"
          element={
            <EnterpriseOnly isCommunity={isCommunity}>
              <IngestionView />
            </EnterpriseOnly>
          }
        />
        <Route
          path="outcomes"
          element={
            <EnterpriseOnly isCommunity={isCommunity}>
              <OutcomesView />
            </EnterpriseOnly>
          }
        />
        <Route
          path="learning"
          element={
            <EnterpriseOnly isCommunity={isCommunity}>
              <LearningView />
            </EnterpriseOnly>
          }
        />
        <Route
          path="reports"
          element={
            <EnterpriseOnly isCommunity={isCommunity}>
              <ReportsView />
            </EnterpriseOnly>
          }
        />
        <Route path="settings" element={<SettingsView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
