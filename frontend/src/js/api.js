const API_BASE = 'http://localhost:8000';

async function fetchGroups() {
  const res = await fetch(`${API_BASE}/groups`);
  if (!res.ok) throw new Error(`HTTP ${res.status} – /groups`);
  return res.json();
}

async function fetchFixtures() {
  const res = await fetch(`${API_BASE}/fixtures`);
  if (!res.ok) throw new Error(`HTTP ${res.status} – /fixtures`);
  return res.json();
}

async function fetchMatchForecast(home, away, stage = 'GROUP_STAGE') {
  const params = new URLSearchParams({ home, away, stage });
  const res = await fetch(`${API_BASE}/forecast/match?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} – /forecast/match`);
  return res.json();
}

async function fetchOdds() {
  const res = await fetch(`${API_BASE}/odds`);
  if (!res.ok) throw new Error(`HTTP ${res.status} – /odds`);
  return res.json();
}

async function fetchOutrightOdds() {
  const res = await fetch(`${API_BASE}/odds/outrights`);
  if (!res.ok) throw new Error(`HTTP ${res.status} – /odds/outrights`);
  return res.json();
}
