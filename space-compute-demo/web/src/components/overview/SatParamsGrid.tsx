import { useTelemetryStore } from '../../store/useTelemetryStore'
import { Metric } from '../primitives'

/**
 * SatParamsGrid — lifts the 14 satellite parameters out of the original
 * StatusCardGrid. Same fields, same formatting, restyled with the param
 * variant from <Metric />. Sourced from the SELECTED satellite (default
 * SAT-07) rather than a global state packet.
 */
export function SatParamsGrid() {
  const sats       = useTelemetryStore((s) => s.sats)
  const selectedId = useTelemetryStore((s) => s.selectedId)
  const sat = sats.find((x) => x.id === selectedId) ?? sats[0]

  // Tone helpers — match original StatusCardGrid thresholds.
  const tempTone =
    sat.temperature_c > 75 ? 'err' :
    sat.temperature_c > 60 ? 'warn' : 'ok'
  const socTone =
    sat.battery_soc < 0.3 ? 'err' :
    sat.battery_soc < 0.5 ? 'warn' : 'ok'

  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-1">
      <Metric size="param" label="Orbit"        value={sat.orbit_type} />
      <Metric size="param" label="Lat / Lon"    value={`${sat.lat.toFixed(2)} / ${sat.lon.toFixed(2)}`} unit="°" />
      <Metric size="param" label="Altitude"     value={sat.altitude_km} digits={0} unit="km" />
      <Metric size="param" label="Sunlit"       value={sat.sunlit ? 'YES' : 'NO'} tone={sat.sunlit ? 'ok' : 'warn'} />
      <Metric size="param" label="Solar In"     value={sat.solar_input_w}   digits={0} unit="W" />
      <Metric size="param" label="Payload Pwr"  value={sat.payload_power_w} digits={0} unit="W" />
      <Metric size="param" label="Platform Pwr" value={sat.platform_power_w} digits={0} unit="W" />
      <Metric size="param" label="GPU"          value={sat.gpu_type} />
      <Metric size="param" label="GPU Util"     value={sat.gpu_utilization * 100} digits={1} unit="%" />
      <Metric size="param" label="Temp"         value={sat.temperature_c} digits={1} unit="°C" tone={tempTone} />
      <Metric size="param" label="Battery SOC"  value={sat.battery_soc * 100} digits={1} unit="%" tone={socTone} />
      <Metric size="param" label="Downlink"     value={sat.downlink_mbps} digits={0} unit="Mbps" />
      <Metric size="param" label="GS Visible"   value={sat.downlink_mbps > 0 ? 'YES' : 'NO'} tone={sat.downlink_mbps > 0 ? 'ok' : 'hi'} />
      <Metric size="param" label="Task"         value={sat.task_state} />
    </div>
  )
}
