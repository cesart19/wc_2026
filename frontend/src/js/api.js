const API_BASE = 'http://localhost:8000';

async function fetchGroups() {
  const res = await fetch(`${API_BASE}/groups`);
  return res.json();
}

async function fetchFixtures() {
  const res = await fetch(`${API_BASE}/fixtures`);
  return res.json();
}
