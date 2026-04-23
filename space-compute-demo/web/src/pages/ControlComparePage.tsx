import { useDemoStore } from '../store/demoStore';
import type { GpuType, OrbitType } from '../types/messages';

const GPU_TYPES: GpuType[] = ['H100', 'H200', 'B200', 'MI300X'];
const ORBITS: OrbitType[] = ['LEO', 'SSO'];

export function ControlComparePage() {
  const params = useDemoStore((s) => s.parameters);
  const setParameters = useDemoStore((s) => s.setParameters);
  const sat = useDemoStore((s) => s.lastState?.satellite);

  return (
    <div className="page page--control">
      <div className="page__side">
        <h3>Parameters</h3>

        <label>Orbit
          <select value={params.orbit_type ?? sat?.orbit_type ?? 'SSO'}
                  onChange={(e) => setParameters({ orbit_type: e.target.value as OrbitType })}>
            {ORBITS.map((o) => <option key={o}>{o}</option>)}
          </select>
        </label>

        <label>GPU
          <select value={params.gpu_type ?? sat?.gpu_type ?? 'H100'}
                  onChange={(e) => setParameters({ gpu_type: e.target.value as GpuType })}>
            {GPU_TYPES.map((g) => <option key={g}>{g}</option>)}
          </select>
        </label>

        <label>Load
          <select value={params.load ?? 'medium'}
                  onChange={(e) => setParameters({ load: e.target.value as 'low' | 'medium' | 'high' })}>
            <option>low</option><option>medium</option><option>high</option>
          </select>
        </label>

        <label>Sunlit
          <input type="checkbox"
                 checked={params.sunlit ?? sat?.sunlit ?? true}
                 onChange={(e) => setParameters({ sunlit: e.target.checked })} />
        </label>
      </div>

      <div className="page__main">
        <h3>Outputs (live)</h3>
        {!sat ? <em>connecting…</em> : (
          <div className="cards">
            <div className="card"><div className="card__label">Solar</div><div className="card__value">{sat.solar_input_w.toFixed(0)} W</div></div>
            <div className="card"><div className="card__label">Payload</div><div className="card__value">{sat.payload_power_w.toFixed(0)} W</div></div>
            <div className="card"><div className="card__label">Temp</div><div className="card__value">{sat.temperature_c.toFixed(1)} °C</div></div>
            <div className="card"><div className="card__label">SOC</div><div className="card__value">{(sat.battery_soc * 100).toFixed(1)} %</div></div>
            <div className="card"><div className="card__label">GPU Util</div><div className="card__value">{(sat.gpu_utilization * 100).toFixed(1)} %</div></div>
            <div className="card"><div className="card__label">Downlink</div><div className="card__value">{sat.downlink_mbps.toFixed(0)} Mbps</div></div>
          </div>
        )}
        <div className="page__note">
          Phase-1 placeholder — dedicated latency / downlink compare charts land in Phase 4.
        </div>
      </div>
    </div>
  );
}
