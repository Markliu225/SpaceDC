import { useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useDemoStore } from '../store/demoStore';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { StreamMount } from './StreamMount';

export function AppShell() {
  const { connected, lastState, connect, play, pause, reset } = useDemoStore();
  const setRunning = useTelemetryStore((s) => s.setRunning);
  const resetTelemetry = useTelemetryStore((s) => s.reset);

  // Mirror header Play / Pause / Reset onto the mock telemetry feed so the
  // new Overview panels honor the same controls as the legacy WebSocket path.
  const handlePlay  = () => { play();  setRunning(true);  };
  const handlePause = () => { pause(); setRunning(false); };
  const handleReset = () => { reset(); resetTelemetry();  setRunning(true); };

  useEffect(() => {
    connect();
  }, [connect]);

  const simTime = lastState?.sim_time_s ?? 0;
  const hours = Math.floor(simTime / 3600);
  const mins = Math.floor((simTime % 3600) / 60);
  const secs = Math.floor(simTime % 60);
  const simTimeStr = `T+${hours.toString().padStart(3, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;

  return (
    <div className="shell">
      <header className="shell__header">
        <div className="shell__brand">SPACE-COMPUTE-DEMO</div>
        <nav className="shell__nav">
          <NavLink to="/" end>Overview</NavLink>
          <NavLink to="/satellite">Satellite Twin</NavLink>
          <NavLink to="/task">Task</NavLink>
          <NavLink to="/control">Control</NavLink>
        </nav>
        <div className="shell__status">
          <span>{simTimeStr}</span>
          <span className={`dot ${connected ? 'dot--ok' : 'dot--bad'}`} />
          <span>{connected ? 'LIVE' : 'OFFLINE'}</span>
          <button onClick={handlePlay}  aria-label="Play">▶</button>
          <button onClick={handlePause} aria-label="Pause">❚❚</button>
          <button onClick={handleReset} aria-label="Reset">⟲</button>
        </div>
      </header>
      <main className="shell__main">
        <Outlet />
      </main>
      {/* Single persistent stream mount; each page's SceneEmbed acts as a positioning slot. */}
      <StreamMount />
    </div>
  );
}
