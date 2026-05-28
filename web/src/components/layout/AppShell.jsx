import { useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Outlet } from 'react-router-dom'

import { getEditionMeta, isCommunityEdition } from '../../api/edition.js'
import { getConfig, patchConfig } from '../../api/enforcement.js'
import { getHealth } from '../../api/dashboard.js'
import Sidebar from './Sidebar.jsx'
import Topbar from './Topbar.jsx'

const ENTERPRISE_MODE_CYCLE = ['off', 'monitor', 'enforce']
const COMMUNITY_MODE_CYCLE = ['off', 'monitor']

export default function AppShell() {
  const queryClient = useQueryClient()
  const [modeBusy, setModeBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const editionQuery = useQuery({
    queryKey: ['meta', 'edition'],
    queryFn: getEditionMeta,
    staleTime: 60_000,
  })

  const isCommunity = isCommunityEdition(editionQuery.data)
  const modeCycle = isCommunity ? COMMUNITY_MODE_CYCLE : ENTERPRISE_MODE_CYCLE

  const configQuery = useQuery({
    queryKey: ['enforcement', 'config'],
    queryFn: getConfig,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  })

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
  })

  const backendLabel = useMemo(() => {
    if (healthQuery.isLoading) return 'Detecting...'
    if (healthQuery.isError) return 'Backend offline'
    const service = String(healthQuery.data?.service || 'valo')
    return `${service.charAt(0).toUpperCase()}${service.slice(1)} backend`
  }, [healthQuery.data, healthQuery.isError, healthQuery.isLoading])

  const mode = configQuery.data?.enforcement_mode || 'monitor'

  const cycleMode = useCallback(async () => {
    if (modeBusy || !configQuery.data) return
    const currentIndex = modeCycle.indexOf(mode)
    const next = modeCycle[(currentIndex + 1) % modeCycle.length]
    setModeBusy(true)
    try {
      await patchConfig({ enforcement_mode: next })
      await queryClient.invalidateQueries({ queryKey: ['enforcement'] })
    } catch {
      // configQuery will surface the error on the Firewall view; nothing to do here
    } finally {
      setModeBusy(false)
    }
  }, [mode, modeBusy, configQuery.data, queryClient, modeCycle])

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    try {
      await queryClient.invalidateQueries()
    } finally {
      setRefreshing(false)
    }
  }, [queryClient])

  return (
    <div className="app-shell">
      <div className="bg-glow bg-glow-a" />
      <div className="bg-glow bg-glow-b" />
      <Sidebar backendLabel={backendLabel} isCommunity={isCommunity} />
      <main className="app-main" id="main-content">
        <Topbar
          mode={mode}
          modeBusy={modeBusy}
          onChangeMode={cycleMode}
          backendLabel={backendLabel}
          onRefresh={handleRefresh}
          refreshing={refreshing}
        />
        <div className="app-main-body">
          <Outlet
            context={{
              config: configQuery.data,
              configQuery,
              edition: editionQuery.data,
              isCommunity,
            }}
          />
        </div>
      </main>
    </div>
  )
}
