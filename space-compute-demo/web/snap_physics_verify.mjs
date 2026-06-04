/**
 * Physics verification harness.
 *
 * Posts several SatelliteConfig combinations to /satellite_config, gives the
 * backend a few ticks to settle, then reads /state and tabulates the relevant
 * physics outputs so we can EYEBALL whether config changes actually drive
 * different results. If they don't, the chain is broken and we fix it before
 * any further iteration.
 */
import http from 'node:http'

function req(method, path, body) {
  return new Promise((resolve, reject) => {
    const data = body ? Buffer.from(JSON.stringify(body)) : null
    const opts = { host: 'localhost', port: 8001, path, method,
      headers: data ? { 'Content-Type': 'application/json', 'Content-Length': data.length } : {} }
    const r = http.request(opts, (x) => { let b = ''; x.on('data', c => b += c); x.on('end', () => resolve(b)) })
    r.on('error', reject); if (data) r.write(data); r.end()
  })
}

const CONFIGS = [
  { name: 'baseline (H100/M/Aluminum)',          cfg: { gpu: 'H100',   solar_material: 'Si',         solar_size: 'M',  radiator_material: 'Aluminum',   radiator_size: 'Standard' } },
  { name: 'big balanced (H100/XL Pero/Graphite)', cfg: { gpu: 'H100',   solar_material: 'Perovskite', solar_size: 'XL', radiator_material: 'Graphite',   radiator_size: 'Wide' } },
  { name: 'huge load (B200/XL Pero/Graphite)',    cfg: { gpu: 'B200',   solar_material: 'Perovskite', solar_size: 'XL', radiator_material: 'Graphite',   radiator_size: 'Wide' } },
  { name: 'small load (MI300X/L GaAs/OSR)',       cfg: { gpu: 'MI300X', solar_material: 'GaAs',       solar_size: 'L',  radiator_material: 'OSR',        radiator_size: 'Standard' } },
  { name: 'starved (H200/S Si/Aluminum)',         cfg: { gpu: 'H200',   solar_material: 'Si',         solar_size: 'S',  radiator_material: 'Aluminum',   radiator_size: 'Compact' } },
]

const fmt = (n, p=1) => (n == null ? '— —' : Number(n).toFixed(p))
const pct = (n) => (n == null ? '— —' : (Math.max(0, Math.min(1, n)) * 100).toFixed(0) + '%')

async function snapshot(label) {
  // Sample three times over a few seconds so a momentary workload-step doesn't bias the read.
  const samples = []
  for (let i = 0; i < 3; i++) {
    const d = JSON.parse(await req('GET', '/state'))
    samples.push(d.satellite)
    await new Promise(r => setTimeout(r, 1500))
  }
  // Aggregate: take the LATEST temperature/SOC (dynamic state), and the
  // MEAN of payload_w / solar_in / radiator_w (smooth out workload step).
  const last = samples[samples.length - 1]
  const mean = (k) => samples.reduce((s, x) => s + (x[k] || 0), 0) / samples.length
  return {
    label,
    workload:    last.workload,
    util:        last.gpu_utilization,
    solar_w:     mean('solar_input_w'),
    payload_w:   mean('payload_power_w'),
    rad_w:       mean('radiator_power_w'),
    net_w:       mean('battery_charge_w'),
    soc:         last.battery_soc,
    cap_wh:      last.battery_capacity_wh,
    temp_c:      last.temperature_c,
    sunlit:      last.sunlit,
    alarms:      last.alarms || [],
  }
}

console.log('\n--- physics verification ---\n')
console.log('Posting configs in sequence, sampling state between each.\n')

const results = []
for (const c of CONFIGS) {
  console.log(`>> ${c.name}`)
  const post = await req('POST', '/satellite_config', c.cfg)
  console.log(`   /satellite_config -> ${post.slice(0, 120)}${post.length > 120 ? '…' : ''}`)
  // Let the backend run several physics ticks under the new config so the
  // battery/thermal state catches up.
  await new Promise(r => setTimeout(r, 6000))
  const s = await snapshot(c.name)
  results.push(s)
}

console.log('\n--- summary table ---\n')
const cols = [
  'config'.padEnd(38),
  'load%'.padStart(6),
  'solar_W'.padStart(9),
  'payload_W'.padStart(10),
  'rad_W'.padStart(8),
  'net_W'.padStart(8),
  'SOC%'.padStart(5),
  'temp_C'.padStart(7),
  'sunlit'.padStart(7),
  'alarms',
]
console.log(cols.join('  '))
for (const r of results) {
  console.log([
    r.label.padEnd(38),
    pct(r.workload).padStart(6),
    fmt(r.solar_w, 0).padStart(9),
    fmt(r.payload_w, 0).padStart(10),
    fmt(r.rad_w, 0).padStart(8),
    (r.net_w >= 0 ? '+' : '') + fmt(r.net_w, 0).padStart(7),
    pct(r.soc).padStart(5),
    fmt(r.temp_c, 1).padStart(7),
    String(r.sunlit).padStart(7),
    r.alarms.join(',') || '-',
  ].join('  '))
}
console.log('')
