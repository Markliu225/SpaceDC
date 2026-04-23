import { useDemoStore } from '../store/demoStore';

const PHASES = ['idle', 'created', 'capturing', 'inferencing', 'packaging', 'downlink', 'delivered'] as const;

export function TaskExecutionPage() {
  const task = useDemoStore((s) => s.task);
  const startTask = useDemoStore((s) => s.startTask);
  const mode = useDemoStore((s) => s.mode);
  const setMode = useDemoStore((s) => s.setMode);

  const current = task?.state ?? 'idle';
  const currentIdx = PHASES.indexOf(current);

  return (
    <div className="page page--task">
      <div className="page__toolbar">
        <button onClick={() => startTask()}>Start Task</button>
        <span className="spacer" />
        <span>MODE</span>
        <button className={mode === 'on_orbit' ? 'on' : ''} onClick={() => setMode('on_orbit')}>On-Orbit</button>
        <button className={mode === 'ground_only' ? 'on' : ''} onClick={() => setMode('ground_only')}>Ground-Only</button>
      </div>

      <div className="task-card">
        {!task ? <em>no task running — click Start Task</em> : (
          <>
            <div><b>{task.id}</b> · {task.type} · <span className="tag">{task.state}</span></div>
            <div>input {task.input_size_mb.toFixed(0)} MB · result {task.result_size_mb.toFixed(1)} MB · progress {(task.progress * 100).toFixed(0)}%</div>
            <div>targets {task.targets} · alerts {task.alerts}</div>
          </>
        )}
      </div>

      <div className="phase-rail">
        {PHASES.map((p, i) => (
          <div key={p} className={`phase ${i === currentIdx ? 'phase--on' : ''} ${i < currentIdx ? 'phase--done' : ''}`}>
            <span className="phase__num">{i + 1}</span>
            <span className="phase__name">{p}</span>
          </div>
        ))}
      </div>

      <div className="page__note">
        Phase-1 placeholder. Full 7-state machine + mock image + detection overlay lands in Phase 3.
      </div>
    </div>
  );
}
