import { useCallback, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import type { WorkloadProfileInfo } from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://127.0.0.1:8001'

/**
 * useWorkloadProfiles — the workload selector's data source. `refresh()`
 * loads every profile annotated with how the CURRENT design copes with it
 * (average demand vs supply, thermal ceiling, fit verdict, expected outputs
 * per cycle); callers re-fetch on open and after design/config changes so
 * the adaptation numbers track the live loadout. The active id rides the
 * broadcast state; switching POSTs and lets the state echo confirm.
 */
export function useWorkloadProfiles() {
  const [profiles, setProfiles] = useState<WorkloadProfileInfo[]>([])
  const [offline, setOffline] = useState(false)
  const [applying, setApplying] = useState(false)
  const active = useDemoStore((s) => s.lastState?.workload_profile) ?? 'balanced'

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/workload_profiles`)
      if (!r.ok) throw new Error(String(r.status))
      const body = (await r.json()) as { active: string; profiles: WorkloadProfileInfo[] }
      setProfiles(body.profiles)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  const applyProfile = useCallback(async (id: string): Promise<boolean> => {
    setApplying(true)
    try {
      const r = await fetch(`${BACKEND_HTTP}/workload_profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile: id }),
      })
      return r.ok
    } catch {
      setOffline(true)
      return false
    } finally {
      setApplying(false)
    }
  }, [])

  return { profiles, active, offline, applying, refresh, applyProfile }
}
