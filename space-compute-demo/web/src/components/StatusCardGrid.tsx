import { useDemoStore } from '../store/demoStore';

interface CardProps { label: string; value: string; unit?: string; tone?: 'ok' | 'warn' | 'bad' }
function Card({ label, value, unit, tone }: CardProps) {
  return (
    <div className={`card ${tone ? `card--${tone}` : ''}`}>
      <div className="card__label">{label}</div>
      <div className="card__value">{value}{unit && <span className="card__unit"> {unit}</span>}</div>
    </div>
  );
}

export function StatusCardGrid() {
  const sat = useDemoStore((s) => s.lastState?.satellite);
  const gs = useDemoStore((s) => s.lastState?.ground_station);
  if (!sat) return <div className="cards"><Card label="waiting" value="—" /></div>;

  const fmt = (x: number, d = 1) => x.toFixed(d);
  return (
    <div className="cards">
      <Card label="Orbit" value={sat.orbit_type} />
      <Card label="Lat / Lon" value={`${fmt(sat.lat, 2)} / ${fmt(sat.lon, 2)}`} unit="°" />
      <Card label="Altitude" value={fmt(sat.altitude_km, 0)} unit="km" />
      <Card label="Sunlit" value={sat.sunlit ? 'YES' : 'NO'} tone={sat.sunlit ? 'ok' : 'warn'} />
      <Card label="Solar In" value={fmt(sat.solar_input_w, 0)} unit="W" />
      <Card label="Payload Pwr" value={fmt(sat.payload_power_w, 0)} unit="W" />
      <Card label="Platform Pwr" value={fmt(sat.platform_power_w, 0)} unit="W" />
      <Card label="GPU" value={sat.gpu_type} />
      <Card label="GPU Util" value={fmt(sat.gpu_utilization * 100, 1)} unit="%" />
      <Card label="Temp" value={fmt(sat.temperature_c, 1)} unit="°C"
            tone={sat.temperature_c > 75 ? 'bad' : sat.temperature_c > 60 ? 'warn' : 'ok'} />
      <Card label="Battery SOC" value={fmt(sat.battery_soc * 100, 1)} unit="%"
            tone={sat.battery_soc < 0.3 ? 'bad' : sat.battery_soc < 0.5 ? 'warn' : 'ok'} />
      <Card label="Downlink" value={fmt(sat.downlink_mbps, 0)} unit="Mbps" />
      <Card label="GS Visible" value={gs?.visible ? 'YES' : 'NO'} tone={gs?.visible ? 'ok' : undefined} />
      <Card label="Task" value={sat.task_state} />
    </div>
  );
}
