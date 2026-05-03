import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { fetchDashboard, fetchMetrics } from '../api';
import { formatDistanceToNow } from 'date-fns';
import { AlertTriangle, Server, Clock, Activity, CheckCircle2 } from 'lucide-react';

const severityColors: Record<string, string> = {
  P0: 'bg-red-500/20 text-red-400 border-red-500/50',
  P1: 'bg-orange-500/20 text-orange-400 border-orange-500/50',
  P2: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50',
  P3: 'bg-blue-500/20 text-blue-400 border-blue-500/50',
};

export default function Dashboard() {
  const queryClient = useQueryClient();

  const { data: incidents, isLoading: incidentsLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: fetchDashboard,
    refetchInterval: 10000,
  });

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_API_BASE_URL?.replace('http', 'ws') || 'ws://localhost:8000';
    const ws = new WebSocket(`${wsUrl}/api/v1/ws/dashboard`);
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        queryClient.setQueryData(['dashboard'], data);
      } catch (e) {
        console.error('Failed to parse websocket message', e);
      }
    };

    return () => {
      ws.close();
    };
  }, [queryClient]);

  const { data: metrics } = useQuery({
    queryKey: ['metrics'],
    queryFn: fetchMetrics,
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-6">
      <div className="glass rounded-xl p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold">Live Incidents</h1>
          <p className="text-slate-400">Monitoring real-time system anomalies</p>
        </div>
        
        {metrics && (
          <div className="flex gap-6 text-sm bg-surface p-4 rounded-lg border border-border">
            <div className="flex flex-col">
              <span className="text-slate-400">Ingestion Rate</span>
              <span className="font-mono text-lg font-bold text-green-400">
                {(metrics.signals_ingested_last_5s / 5).toFixed(1)} /s
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-slate-400">Queue Depth</span>
              <span className="font-mono text-lg font-bold text-blue-400">
                {metrics.queue_depth}
              </span>
            </div>
          </div>
        )}
      </div>

      {incidentsLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="glass rounded-xl p-6 h-48 animate-pulse" />
          ))}
        </div>
      ) : !incidents || incidents.length === 0 ? (
        <div className="glass rounded-xl p-12 flex flex-col items-center justify-center text-center space-y-4">
          <div className="relative">
            <div className="absolute inset-0 bg-green-500/20 rounded-full animate-ping" />
            <CheckCircle2 className="w-16 h-16 text-green-500 relative z-10 bg-surface rounded-full" />
          </div>
          <h2 className="text-xl font-medium text-slate-300">No active incidents</h2>
          <p className="text-slate-500">System is healthy 🟢</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {incidents.map((incident: any) => (
            <Link 
              key={incident.id} 
              to={`/incidents/${incident.id}`}
              className="glass rounded-xl p-6 hover:bg-surface/90 transition-colors border-l-4 group"
              style={{ borderLeftColor: incident.severity === 'P0' ? '#ef4444' : incident.severity === 'P1' ? '#f97316' : incident.severity === 'P2' ? '#eab308' : '#3b82f6' }}
            >
              <div className="flex justify-between items-start mb-4">
                <span className={`px-2.5 py-1 rounded-md text-xs font-bold border ${severityColors[incident.severity] || 'bg-slate-800 text-white border-slate-600'}`}>
                  {incident.severity}
                </span>
                <span className="px-2.5 py-1 rounded-md text-xs font-medium bg-surface border border-border text-slate-300">
                  {incident.status}
                </span>
              </div>
              
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-slate-200 font-medium">
                  <Server className="w-4 h-4 text-slate-400" />
                  <span className="truncate">{incident.component_id}</span>
                </div>
                
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <AlertTriangle className="w-4 h-4" />
                  <span className="truncate">{incident.alert_type}</span>
                </div>
                
                <div className="flex justify-between items-center text-sm pt-4 border-t border-border/50">
                  <div className="flex items-center gap-1.5 text-slate-400">
                    <Activity className="w-4 h-4 text-indigo-400" />
                    <span>{incident.signal_count} signals</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-slate-400">
                    <Clock className="w-4 h-4 text-blue-400" />
                    <span>{formatDistanceToNow(new Date(incident.start_time))}</span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
