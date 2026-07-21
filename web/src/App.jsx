import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { getEditionMeta, isCommunityEdition } from './api/edition.js'
import EnterpriseGate from './components/EnterpriseGate.jsx'
import AppShell from './components/layout/AppShell.jsx'
import AnalysisView from './views/AnalysisView.jsx'
import DemoView from './views/DemoView.jsx'
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

export default function App() {
  const editionQuery = useQuery({
    queryKey: ['meta', 'edition'],
    queryFn: getEditionMeta,
    staleTime: 60_000,
  })
  const isCommunity = isCommunityEdition(editionQuery.data)

  return (
    <Routes>
      <Route element={<AppShell isCommunity={isCommunity} />}>
        <Route index element={<OverviewView />} />
        <Route path="demo" element={<DemoView />} />
        <Route
          path="executive"
          element={
            <EnterpriseGate feature="executive">
              <ExecutiveView />
            </EnterpriseGate>
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
            <EnterpriseGate feature="ingestion">
              <IngestionView />
            </EnterpriseGate>
          }
        />
        <Route
          path="outcomes"
          element={
            <EnterpriseGate feature="outcomes">
              <OutcomesView />
            </EnterpriseGate>
          }
        />
        <Route
          path="learning"
          element={
            <EnterpriseGate feature="learning">
              <LearningView />
            </EnterpriseGate>
          }
        />
        <Route
          path="reports"
          element={
            <EnterpriseGate feature="reports">
              <ReportsView />
            </EnterpriseGate>
          }
        />
        <Route path="settings" element={<SettingsView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
