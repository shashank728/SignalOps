import React, { useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchWorkItem, fetchSignals, updateStatus, fetchRCA, submitRCA } from '../api';
import { format } from 'date-fns';
import { ArrowLeft, Server, AlertTriangle, Activity, CheckCircle, ShieldAlert, XCircle } from 'lucide-react';

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('overview');
  const [page, setPage] = useState(1);
  const [rcaError, setRcaError] = useState('');

  const { data: workItem, isLoading, isError } = useQuery({
    queryKey: ['workItem', id],
    queryFn: () => fetchWorkItem(id!),
    enabled: !!id,
  });

  const { data: signalsData, isLoading: signalsLoading } = useQuery({
    queryKey: ['signals', id, page],
    queryFn: () => fetchSignals(id!, page),
    enabled: !!id && activeTab === 'signals',
  });

  const { data: rcaData, isLoading: rcaLoading } = useQuery({
    queryKey: ['rca', id],
    queryFn: () => fetchRCA(id!),
    enabled: !!id && activeTab === 'rca',
  });

  const statusMutation = useMutation({
    mutationFn: (newStatus: string) => updateStatus(id!, newStatus),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workItem', id] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (err: any) => {
      alert(`Failed to update status: ${err?.detail || err?.message || 'Unknown error'}`);
    }
  });

  if (isLoading) return <div className="p-12 text-center text-slate-400">Loading incident details...</div>;
  if (isError || !workItem) return <div className="p-12 text-center text-red-400">Error loading incident or not found.</div>;

  const handleStatusChange = () => {
    if (workItem.status === 'OPEN') statusMutation.mutate('INVESTIGATING');
    else if (workItem.status === 'INVESTIGATING') statusMutation.mutate('RESOLVED');
    else if (workItem.status === 'RESOLVED') {
      if (!rcaData && activeTab !== 'rca') {
        alert("You must submit a Root Cause Analysis before closing this incident.");
        setActiveTab('rca');
      } else {
        statusMutation.mutate('CLOSED');
      }
    }
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-in fade-in duration-500">
      <Link to="/" className="inline-flex items-center gap-2 text-slate-400 hover:text-white transition-colors">
        <ArrowLeft className="w-4 h-4" />
        Back to Dashboard
      </Link>

      <div className="glass rounded-xl p-6 border-l-4" style={{ borderLeftColor: workItem.severity === 'P0' ? '#ef4444' : workItem.severity === 'P1' ? '#f97316' : workItem.severity === 'P2' ? '#eab308' : '#3b82f6' }}>
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="px-2.5 py-1 rounded-md text-xs font-bold border bg-surface text-white border-slate-600">
                {workItem.severity}
              </span>
              <span className={`px-2.5 py-1 rounded-md text-xs font-bold border ${
                workItem.status === 'OPEN' ? 'bg-red-500/20 text-red-400 border-red-500/50' :
                workItem.status === 'INVESTIGATING' ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/50' :
                workItem.status === 'RESOLVED' ? 'bg-blue-500/20 text-blue-400 border-blue-500/50' :
                'bg-green-500/20 text-green-400 border-green-500/50'
              }`}>
                {workItem.status}
              </span>
            </div>
            <h1 className="text-2xl font-bold flex items-center gap-2">
              <Server className="w-6 h-6 text-slate-400" />
              {workItem.component_id}
            </h1>
            <p className="text-slate-400 flex items-center gap-2 mt-1">
              <AlertTriangle className="w-4 h-4" /> {workItem.alert_type}
            </p>
          </div>

          <div className="flex flex-col items-end gap-2">
            <div className="text-sm text-slate-400">
              Started: {format(new Date(workItem.start_time), 'MMM d, yyyy HH:mm:ss')}
            </div>
            {workItem.status !== 'CLOSED' && (
              <button
                onClick={handleStatusChange}
                disabled={statusMutation.isPending}
                className="px-4 py-2 rounded-lg font-medium text-sm transition-all bg-primary hover:bg-blue-600 text-white disabled:opacity-50"
              >
                {statusMutation.isPending ? 'Updating...' :
                 workItem.status === 'OPEN' ? 'Start Investigation' :
                 workItem.status === 'INVESTIGATING' ? 'Mark Resolved' :
                 'Close Incident'}
              </button>
            )}
            {workItem.status === 'CLOSED' && (
              <div className="flex items-center gap-2 text-green-400 font-medium">
                <CheckCircle className="w-5 h-5" /> Closed
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex border-b border-border">
        {['overview', 'signals', 'rca'].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === tab ? 'border-primary text-white bg-surface/50' : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-surface/30'}`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {activeTab === 'overview' && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="glass rounded-xl p-6 space-y-4">
              <h3 className="font-semibold text-lg border-b border-border pb-2">Incident Details</h3>
              <div className="grid grid-cols-2 gap-y-4 text-sm">
                <div className="text-slate-400">Component Type</div>
                <div className="font-medium">{workItem.component_type}</div>
                
                <div className="text-slate-400">Signal Count</div>
                <div className="font-medium flex items-center gap-1">
                  <Activity className="w-4 h-4 text-indigo-400" />
                  {workItem.signal_count}
                </div>
                
                {workItem.end_time && (
                  <>
                    <div className="text-slate-400">Resolved At</div>
                    <div className="font-medium">{format(new Date(workItem.end_time), 'MMM d, HH:mm:ss')}</div>
                  </>
                )}
                
                {workItem.mttr_seconds && (
                  <>
                    <div className="text-slate-400">MTTR</div>
                    <div className="font-medium text-blue-400">{Math.floor(workItem.mttr_seconds / 60)} minutes</div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'signals' && (
          <div className="glass rounded-xl overflow-hidden">
            {signalsLoading ? (
              <div className="p-8 text-center text-slate-400">Loading signals...</div>
            ) : signalsData?.data?.length === 0 ? (
              <div className="p-8 text-center text-slate-400">No signals linked yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-left">
                  <thead className="text-xs text-slate-400 uppercase bg-surface/50 border-b border-border">
                    <tr>
                      <th className="px-6 py-3">Timestamp</th>
                      <th className="px-6 py-3">Error Code</th>
                      <th className="px-6 py-3">Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signalsData?.data.map((sig: any) => (
                      <tr key={sig._id} className="border-b border-border hover:bg-surface/50">
                        <td className="px-6 py-4 whitespace-nowrap text-slate-300">
                          {format(new Date(sig.timestamp), 'HH:mm:ss.SSS')}
                        </td>
                        <td className="px-6 py-4 font-mono text-xs text-red-400">{sig.error_code}</td>
                        <td className="px-6 py-4 text-slate-300">{sig.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="p-4 flex justify-between items-center border-t border-border bg-surface/30">
                  <button 
                    disabled={page === 1}
                    onClick={() => setPage(p => p - 1)}
                    className="px-3 py-1 bg-surface rounded text-slate-300 disabled:opacity-50 border border-border"
                  >Previous</button>
                  <span className="text-slate-400 text-sm">Page {page}</span>
                  <button 
                    disabled={signalsData?.data?.length < 50}
                    onClick={() => setPage(p => p + 1)}
                    className="px-3 py-1 bg-surface rounded text-slate-300 disabled:opacity-50 border border-border"
                  >Next</button>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'rca' && (
          <RCAForm 
            workItem={workItem} 
            existingRCA={rcaData} 
            loading={rcaLoading} 
            onSubmit={async (data: any) => {
              try {
                await submitRCA(id!, data);
                queryClient.invalidateQueries({ queryKey: ['rca', id] });
                setRcaError('');
              } catch (err: any) {
                setRcaError(err?.detail?.message || 'Failed to submit RCA');
              }
            }} 
            error={rcaError}
          />
        )}
      </div>
    </div>
  );
}

function RCAForm({ workItem, existingRCA, loading, onSubmit, error }: any) {
  const [formData, setFormData] = useState({
    incident_start: workItem.start_time.slice(0, 16),
    incident_end: workItem.end_time ? workItem.end_time.slice(0, 16) : new Date().toISOString().slice(0, 16),
    root_cause_category: 'Unknown',
    fix_applied: '',
    prevention_steps: ''
  });
  const [submitting, setSubmitting] = useState(false);

  if (loading) return <div className="p-8 text-center text-slate-400">Loading RCA...</div>;

  if (existingRCA) {
    return (
      <div className="glass rounded-xl p-6 space-y-6">
        <div className="flex items-center gap-2 text-green-400 mb-4 pb-4 border-b border-border">
          <ShieldAlert className="w-5 h-5" />
          <h3 className="font-bold text-lg text-white">Root Cause Analysis Submitted</h3>
        </div>
        
        <div className="grid grid-cols-2 gap-6 text-sm">
          <div>
            <div className="text-slate-400 mb-1">Incident Start</div>
            <div className="bg-surface p-3 rounded border border-border">{format(new Date(existingRCA.incident_start), 'PPpp')}</div>
          </div>
          <div>
            <div className="text-slate-400 mb-1">Incident End</div>
            <div className="bg-surface p-3 rounded border border-border">{format(new Date(existingRCA.incident_end), 'PPpp')}</div>
          </div>
          <div className="col-span-2">
            <div className="text-slate-400 mb-1">Root Cause Category</div>
            <div className="bg-surface p-3 rounded border border-border inline-block text-yellow-400 font-medium">{existingRCA.root_cause_category}</div>
          </div>
          <div className="col-span-2">
            <div className="text-slate-400 mb-1">Fix Applied</div>
            <div className="bg-surface p-4 rounded border border-border text-slate-300 whitespace-pre-wrap">{existingRCA.fix_applied}</div>
          </div>
          <div className="col-span-2">
            <div className="text-slate-400 mb-1">Prevention Steps</div>
            <div className="bg-surface p-4 rounded border border-border text-slate-300 whitespace-pre-wrap">{existingRCA.prevention_steps}</div>
          </div>
        </div>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    await onSubmit({
      ...formData,
      incident_start: new Date(formData.incident_start).toISOString(),
      incident_end: new Date(formData.incident_end).toISOString(),
    });
    setSubmitting(false);
  };

  const isValid = formData.fix_applied.length >= 20 && formData.prevention_steps.length >= 20 && new Date(formData.incident_end) > new Date(formData.incident_start);

  return (
    <form onSubmit={handleSubmit} className="glass rounded-xl p-6 space-y-6">
      <h3 className="font-bold text-lg border-b border-border pb-2">Submit Root Cause Analysis</h3>
      
      {error && (
        <div className="bg-red-500/10 border border-red-500/50 text-red-400 p-4 rounded-lg flex items-center gap-2">
          <XCircle className="w-5 h-5" /> {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label className="block text-sm text-slate-400 mb-1">Incident Start *</label>
          <input 
            type="datetime-local" 
            value={formData.incident_start}
            onChange={e => setFormData(f => ({...f, incident_start: e.target.value}))}
            className="w-full bg-surface border border-border rounded-lg p-2.5 text-white focus:ring-2 focus:ring-primary outline-none"
            required
          />
        </div>
        <div>
          <label className="block text-sm text-slate-400 mb-1">Incident End *</label>
          <input 
            type="datetime-local" 
            value={formData.incident_end}
            onChange={e => setFormData(f => ({...f, incident_end: e.target.value}))}
            className="w-full bg-surface border border-border rounded-lg p-2.5 text-white focus:ring-2 focus:ring-primary outline-none"
            required
          />
        </div>
        <div className="col-span-1 md:col-span-2">
          <label className="block text-sm text-slate-400 mb-1">Root Cause Category *</label>
          <select 
            value={formData.root_cause_category}
            onChange={e => setFormData(f => ({...f, root_cause_category: e.target.value}))}
            className="w-full bg-surface border border-border rounded-lg p-2.5 text-white focus:ring-2 focus:ring-primary outline-none"
          >
            {["Infrastructure Failure", "Software Bug", "Configuration Error", "Human Error", "Third-Party Dependency", "Capacity Exhaustion", "Security Incident", "Unknown"].map(opt => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
        
        <div className="col-span-1 md:col-span-2">
          <div className="flex justify-between mb-1 text-sm text-slate-400">
            <label>Fix Applied *</label>
            <span className={formData.fix_applied.length < 20 ? 'text-red-400' : 'text-green-400'}>{formData.fix_applied.length}/20 min</span>
          </div>
          <textarea 
            rows={4}
            value={formData.fix_applied}
            onChange={e => setFormData(f => ({...f, fix_applied: e.target.value}))}
            className="w-full bg-surface border border-border rounded-lg p-3 text-white focus:ring-2 focus:ring-primary outline-none"
            placeholder="Describe the technical fix applied..."
            required
          />
        </div>

        <div className="col-span-1 md:col-span-2">
          <div className="flex justify-between mb-1 text-sm text-slate-400">
            <label>Prevention Steps *</label>
            <span className={formData.prevention_steps.length < 20 ? 'text-red-400' : 'text-green-400'}>{formData.prevention_steps.length}/20 min</span>
          </div>
          <textarea 
            rows={4}
            value={formData.prevention_steps}
            onChange={e => setFormData(f => ({...f, prevention_steps: e.target.value}))}
            className="w-full bg-surface border border-border rounded-lg p-3 text-white focus:ring-2 focus:ring-primary outline-none"
            placeholder="Describe steps to prevent recurrence..."
            required
          />
        </div>
      </div>

      <div className="flex justify-end pt-4">
        <button 
          type="submit" 
          disabled={!isValid || submitting}
          className="bg-primary hover:bg-blue-600 disabled:opacity-50 text-white px-6 py-2.5 rounded-lg font-medium transition-colors"
        >
          {submitting ? 'Submitting...' : 'Submit RCA'}
        </button>
      </div>
    </form>
  );
}
