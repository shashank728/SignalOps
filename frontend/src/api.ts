const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

export const fetchDashboard = async () => {
  const res = await fetch(`${BASE_URL}/dashboard`);
  if (!res.ok) throw new Error('Failed to fetch dashboard');
  return res.json();
};

export const fetchMetrics = async () => {
  const res = await fetch(`${BASE_URL}/metrics`);
  if (!res.ok) throw new Error('Failed to fetch metrics');
  return res.json();
};

export const fetchWorkItem = async (id: string) => {
  const res = await fetch(`${BASE_URL}/work-items/${id}`);
  if (!res.ok) throw new Error('Failed to fetch work item');
  return res.json();
};

export const fetchSignals = async (id: string, page = 1) => {
  const res = await fetch(`${BASE_URL}/work-items/${id}/signals?page=${page}&limit=50`);
  if (!res.ok) throw new Error('Failed to fetch signals');
  return res.json();
};

export const updateStatus = async (id: string, status: string) => {
  const res = await fetch(`${BASE_URL}/work-items/${id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });
  if (!res.ok) {
    const error = await res.json();
    throw error;
  }
  return res.json();
};

export const fetchRCA = async (id: string) => {
  const res = await fetch(`${BASE_URL}/work-items/${id}/rca`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error('Failed to fetch RCA');
  return res.json();
};

export const submitRCA = async (id: string, data: any) => {
  const res = await fetch(`${BASE_URL}/work-items/${id}/rca`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  if (!res.ok) {
    const error = await res.json();
    throw error;
  }
  return res.json();
};
