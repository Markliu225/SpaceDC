import { useEffect } from 'react';
import { SceneEmbed } from '../components/SceneEmbed';
import { StatusCardGrid } from '../components/StatusCardGrid';
import { useDemoStore } from '../store/demoStore';

export function OverviewPage() {
  const eventLog = useDemoStore((s) => s.eventLog);
  const changeCamera = useDemoStore((s) => s.changeCamera);
  const connected = useDemoStore((s) => s.connected);
  useEffect(() => {
    if (connected) changeCamera('overview');
  }, [connected, changeCamera]);
  return (
    <div className="page page--overview">
      <div className="page__scene"><SceneEmbed cameraPreset="overview" /></div>
      <div className="page__side">
        <StatusCardGrid />
      </div>
      <div className="page__bottom">
        <div className="eventlog">
          <div className="eventlog__title">EVENT LOG</div>
          {eventLog.length === 0 ? <div className="eventlog__empty">— no events —</div> :
            eventLog.slice(-8).map((l, i) => <div key={i} className="eventlog__row">{l}</div>)}
        </div>
      </div>
    </div>
  );
}
