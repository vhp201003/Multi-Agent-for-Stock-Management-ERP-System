import React, { useEffect, useState } from 'react';
import './WorkerDashboard.css';

interface WorkerInstance {
  [instanceId: string]: string; // instance_id -> status
}

interface WorkerInstances {
  [agentType: string]: WorkerInstance;
}

interface QueueMetrics {
  [agentType: string]: {
    active: number;
    pending: number;
  };
}

interface WorkerInstancesData {
  instances: WorkerInstances;
  total_workers: number;
}

interface QueueMetricsData {
  queues: QueueMetrics;
}

const WorkerDashboard: React.FC = () => {
  const [instances, setInstances] = useState<WorkerInstances>({});
  const [queues, setQueues] = useState<QueueMetrics>({});
  const [totalWorkers, setTotalWorkers] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
        const [instancesRes, queuesRes] = await Promise.all([
          fetch(`${baseUrl}/admin/worker-instances`).then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
          }),
          fetch(`${baseUrl}/admin/queue-metrics`).then(r => {
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
          })
        ]);

        const instancesData = instancesRes as WorkerInstancesData;
        const queuesData = queuesRes as QueueMetricsData;

        setInstances(instancesData.instances);
        setTotalWorkers(instancesData.total_workers);
        setQueues(queuesData.queues);
        setError(null);
      } catch (err) {
        console.error('Failed to fetch metrics:', err);
        setError('Failed to load dashboard data');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 3000); // Refresh every 3s
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: string): string => {
    switch (status.toLowerCase()) {
      case 'idle': return '#4caf50';
      case 'processing': return '#ff9800';
      case 'error': return '#f44336';
      default: return '#9e9e9e';
    }
  };

  const getIdleCount = (): number => {
    return Object.values(instances)
      .flatMap(workers => Object.values(workers))
      .filter(status => status === 'IDLE').length;
  };

  const getProcessingCount = (): number => {
    return Object.values(instances)
      .flatMap(workers => Object.values(workers))
      .filter(status => status === 'PROCESSING').length;
  };

  const getTotalQueuedTasks = (): number => {
    return Object.values(queues).reduce(
      (sum, queue) => sum + queue.active + queue.pending,
      0
    );
  };

  if (loading && totalWorkers === 0) {
    return (
      <div className="worker-dashboard loading">
        <div className="loading-spinner" />
        <p>Loading dashboard...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="worker-dashboard error">
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="worker-dashboard">
      <div className="dashboard-header">
        <h1>Multi-Instance Worker Dashboard</h1>
        <div className="header-stats">
          <div className="stat-card">
            <div className="stat-value">{totalWorkers}</div>
            <div className="stat-label">Total Workers</div>
          </div>
          <div className="stat-card idle">
            <div className="stat-value">{getIdleCount()}</div>
            <div className="stat-label">Idle Workers</div>
          </div>
          <div className="stat-card processing">
            <div className="stat-value">{getProcessingCount()}</div>
            <div className="stat-label">Processing</div>
          </div>
          <div className="stat-card queued">
            <div className="stat-value">{getTotalQueuedTasks()}</div>
            <div className="stat-label">Queued Tasks</div>
          </div>
        </div>
      </div>

      <div className="dashboard-grid">
        {Object.entries(instances).map(([agentType, workers]) => {
          const queueData = queues[agentType] || { active: 0, pending: 0 };
          const workerCount = Object.keys(workers).length;
          const idleWorkers = Object.values(workers).filter(s => s === 'IDLE').length;

          return (
            <div key={agentType} className="agent-card">
              <div className="agent-header">
                <div className="agent-title">
                  <h3>{agentType.toUpperCase()}</h3>
                  <span className="worker-count">{workerCount} workers</span>
                </div>
                <div className="agent-summary">
                  <span className="idle-count">{idleWorkers} idle</span>
                </div>
              </div>

              <div className="worker-instances">
                {Object.entries(workers).map(([instanceId, status]) => (
                  <div key={instanceId} className="instance-row">
                    <div className="instance-info">
                      <div
                        className="status-dot"
                        style={{ backgroundColor: getStatusColor(status) }}
                      />
                      <span className="instance-id">{instanceId}</span>
                    </div>
                    <span className={`instance-status ${status.toLowerCase()}`}>
                      {status}
                    </span>
                  </div>
                ))}
              </div>

              <div className="queue-info">
                <div className="queue-stat">
                  <span className="queue-label">Active Queue:</span>
                  <span className="queue-value active">{queueData.active}</span>
                </div>
                <div className="queue-stat">
                  <span className="queue-label">Pending Queue:</span>
                  <span className="queue-value pending">{queueData.pending}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default WorkerDashboard;
