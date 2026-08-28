import { useCallback, useEffect, useState } from 'react'
import { useDemoStore } from '../store/demoStore'
import type { SatelliteAssetInfo, SatelliteAssetsResponse } from '../types/messages'

const BACKEND_HTTP =
  (import.meta.env.VITE_BACKEND_HTTP as string | undefined) ?? 'http://127.0.0.1:8001'

/** Absolute URL for a platform's software-rendered thumbnail. */
export function assetPreviewSrc(asset: SatelliteAssetInfo): string {
  return `${BACKEND_HTTP}${asset.preview_url}`
}

/**
 * useSatelliteAssets — the buildable vendor platforms (GET /satellite_assets).
 * Loads once on mount; the live `asset_id` in the broadcast state wins over
 * the fetched one, so applying a design preset (which also changes the hull)
 * moves the highlight without a refetch.
 */
export function useSatelliteAssets() {
  const [assets, setAssets] = useState<SatelliteAssetInfo[]>([])
  const [fetchedActive, setFetchedActive] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)

  const liveActive = useDemoStore((s) => s.lastState?.asset_id)
  const activeId = liveActive ?? fetchedActive

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_HTTP}/satellite_assets`)
      if (!r.ok) throw new Error(`${r.status}`)
      const body = (await r.json()) as SatelliteAssetsResponse
      setAssets(body.assets)
      setFetchedActive(body.active)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  return { assets, activeId, offline, refresh }
}
