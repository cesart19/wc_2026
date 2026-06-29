const REFRESH_INTERVAL = 60000;
const STAGE_LABELS = {
  GROUP_STAGE:   'Fase de Grupos',
  LAST_32:       'Ronda de 32',
  LAST_16:       'Ronda de 16',
  QUARTER_FINALS:'Cuartos de Final',
  SEMI_FINALS:   'Semifinales',
  THIRD_PLACE:   'Tercer Lugar',
  FINAL:         'Final',
};

// Full knockout bracket: matchId → { home slot, away slot }
// Group-stage slots: w_ = winner, r_ = runner-up, t_ = best 3rd from listed groups
// Knockout slots:    win_XXXXXX = winner of match XXXXXX, lose_XXXXXX = loser
const KNOCKOUT_BRACKET = {
  // ── LAST_32 ──────────────────────────────────────────────────────────
  537417: { home: 'r_A',        away: 'r_B'        },
  537423: { home: 'w_C',        away: 'r_F'        },
  537415: { home: 'w_E',        away: 't_ABCDF'    },
  537418: { home: 'w_F',        away: 'r_C'        },
  537424: { home: 'r_E',        away: 'r_I'        },
  537416: { home: 'w_I',        away: 't_CDFGH'    },
  537425: { home: 'w_A',        away: 't_CEFHI'    },
  537426: { home: 'w_L',        away: 't_EHIJK'    },
  537422: { home: 'w_D',        away: 't_BEFIJ'    },
  537421: { home: 'w_G',        away: 't_AEHIJ'    },
  537420: { home: 'r_K',        away: 'r_L'        },
  537419: { home: 'w_H',        away: 'r_J'        },
  537429: { home: 'w_B',        away: 't_EFGIJ'    },
  537428: { home: 'w_J',        away: 'r_H'        },
  537427: { home: 'w_K',        away: 't_DEIJL'    },
  537430: { home: 'r_D',        away: 'r_G'        },
  // ── LAST_16 (winners of LAST_32 pairs) ───────────────────────────────
  537376: { home: 'win_537417', away: 'win_537415' },
  537375: { home: 'win_537416', away: 'win_537424' },
  537377: { home: 'win_537418', away: 'win_537423' },
  537378: { home: 'win_537425', away: 'win_537426' },
  537379: { home: 'win_537422', away: 'win_537421' },
  537380: { home: 'win_537429', away: 'win_537428' },
  537381: { home: 'win_537420', away: 'win_537419' },
  537382: { home: 'win_537427', away: 'win_537430' },
  // ── QUARTER_FINALS ───────────────────────────────────────────────────
  537383: { home: 'win_537376', away: 'win_537375' },
  537384: { home: 'win_537377', away: 'win_537378' },
  537385: { home: 'win_537379', away: 'win_537380' },
  537386: { home: 'win_537381', away: 'win_537382' },
  // ── SEMI_FINALS ──────────────────────────────────────────────────────
  537387: { home: 'win_537383', away: 'win_537384' },
  537388: { home: 'win_537385', away: 'win_537386' },
  // ── 3RD PLACE ────────────────────────────────────────────────────────
  537389: { home: 'lose_537387', away: 'lose_537388' },
  // ── FINAL ────────────────────────────────────────────────────────────
  537390: { home: 'win_537387', away: 'win_537388' },
};

let currentStageFilter = 'ALL';
let allFixtures = [];
let baseGroups = [];
let currentSimGroups = [];
let countdown;
let simulations = JSON.parse(localStorage.getItem('wc_simulations') || '{}');
// matchId → { homeWin, draw, awayWin, model: {homeWin,draw,awayWin}, market: {...}|null }
// homeWin/draw/awayWin son las probs de display (blended si hay mercado, modelo si no)
let forecasts = {};

function saveSimulation(matchId, result) {
  const key = String(matchId);
  if (simulations[key] === result) {
    delete simulations[key];
  } else {
    simulations[key] = result;
  }
  localStorage.setItem('wc_simulations', JSON.stringify(simulations));
  renderGroups();    // updates currentSimGroups first
  renderFixtures();  // then re-renders fixtures with updated projections
}

// Wipe every "what-if" simulation and forecast pick, then re-render so the
// group tables fall back to the real standings from the API.
function clearAllSimulations() {
  if (!Object.keys(simulations).length) return;
  simulations = {};
  forecasts = {};
  localStorage.removeItem('wc_simulations');
  renderGroups();
  renderFixtures();
}

// Keep the header "Limpiar simulaciones" button in sync with the active count:
// hidden when there is nothing to clear, otherwise shows the running total.
function updateClearSimsButton() {
  const btn = document.getElementById('clear-sims-btn');
  if (!btn) return;
  const count = Object.keys(simulations).length;
  btn.hidden = count === 0;
  const countEl = document.getElementById('clear-sims-count');
  if (countEl) countEl.textContent = count ? `(${count})` : '';
}

// --- TAB NAVIGATION ---
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});

// --- GROUPS ---
async function loadGroups() {
  const container = document.getElementById('groups-container');
  try {
    baseGroups = await fetchGroups();
    renderGroups();
  } catch (e) {
    container.innerHTML = `<div class="error">Error cargando grupos: ${e.message}</div>`;
  }
}

function applySimulationsToGroups(groups) {
  if (!Object.keys(simulations).length || !allFixtures.length) return groups;

  const cloned = JSON.parse(JSON.stringify(groups));
  const byId = {};
  const byName = {};
  cloned.forEach(g => g.table.forEach(row => {
    if (row.teamId) byId[row.teamId] = row;
    if (row.team)   byName[row.team.toLowerCase()] = row;
  }));

  const findTeam = (id, name) =>
    (id && byId[id]) || (name && byName[name.toLowerCase()]) || null;

  Object.entries(simulations).forEach(([matchId, result]) => {
    const match = allFixtures.find(m => String(m.id) === matchId);
    if (!match || !['TIMED', 'SCHEDULED'].includes(match.status)) return;

    const home = findTeam(match.homeTeam.id, match.homeTeam.name);
    const away = findTeam(match.awayTeam.id, match.awayTeam.name);
    if (!home || !away) return;

    home.played++;
    away.played++;
    home._sim = true;
    away._sim = true;

    if (result === 'HOME') {
      home.won++;  home.points += 3;  home.gf += 2; home.ga += 1;
      away.lost++;                    away.gf += 1; away.ga += 2;
    } else if (result === 'AWAY') {
      away.won++;  away.points += 3;  away.gf += 2; away.ga += 1;
      home.lost++;                    home.gf += 1; home.ga += 2;
    } else {
      home.draw++; home.points++;     home.gf += 1; home.ga += 1;
      away.draw++; away.points++;     away.gf += 1; away.ga += 1;
    }
    home.gd = home.gf - home.ga;
    away.gd = away.gf - away.ga;
  });

  cloned.forEach(g => {
    g.table.sort((a, b) => b.points - a.points || b.gd - a.gd || b.gf - a.gf);
    g.table.forEach((row, i) => { row.position = i + 1; });
    g._hasSim = g.table.some(r => r._sim);
  });

  return cloned;
}

function renderGroups() {
  const container = document.getElementById('groups-container');
  if (!baseGroups.length) {
    container.innerHTML = '<div class="loading">Sin datos de grupos todavía.</div>';
    return;
  }
  const groups = applySimulationsToGroups(baseGroups);
  currentSimGroups = groups;
  container.innerHTML = `<div class="groups-grid">${groups.map(renderGroupCard).join('')}</div>`;
  updateClearSimsButton();
}

// Returns { 't_ABCDF': teamObj, 't_CDFGH': teamObj, ... } using the official
// FIFA Annex C allocation table (all 495 combinations of 8 qualifying groups).
function computeThirdPlaceAssignments() {
  const all3rds = currentSimGroups
    .filter(g => g.table.length >= 3 && g.table[2])
    .map(g => ({ ...g.table[2], groupLetter: g.group.slice(-1) }))
    .sort((a, b) => b.points - a.points || b.gd - a.gd || b.gf - a.gf);
  const top8 = all3rds.slice(0, 8);
  const key = top8.map(t => t.groupLetter).sort().join('');
  const slotMap = THIRD_PLACE_LOOKUP[key];
  if (!slotMap) return {};
  const result = {};
  for (const [slot, letter] of Object.entries(slotMap)) {
    const team = top8.find(t => t.groupLetter === letter);
    if (team) result[slot] = team;
  }
  return result;
}

function getProjectedTeam(slot) {
  if (slot.startsWith('win_') || slot.startsWith('lose_')) {
    const matchId = parseInt(slot.replace(/^(win|lose)_/, ''));
    return getKnockoutProjectedTeam(matchId, slot.startsWith('win_'));
  }
  if (!currentSimGroups.length || !Object.keys(simulations).length) return null;
  const type = slot[0]; // 'w', 'r', or 't'
  const letters = slot.slice(2).split('');
  if (type === 'w' || type === 'r') {
    const pos = type === 'w' ? 0 : 1;
    const g = currentSimGroups.find(sg => sg.group === `Group ${letters[0]}`);
    return (g && g.table[pos]) ? g.table[pos] : null;
  }
  // t_ slot: use global top-8 assignment to guarantee uniqueness
  const assignments = computeThirdPlaceAssignments();
  return assignments[slot] || null;
}

function resolveMatchTeam(match, side) {
  const apiTeam = side === 'home' ? match.homeTeam : match.awayTeam;
  if (apiTeam.name && apiTeam.name !== 'TBD') {
    return { team: apiTeam.name, crest: apiTeam.crest, teamId: apiTeam.id };
  }
  const bracket = KNOCKOUT_BRACKET[match.id];
  if (!bracket) return null;
  return getProjectedTeam(side === 'home' ? bracket.home : bracket.away);
}

function getKnockoutProjectedTeam(matchId, wantWinner) {
  const match = allFixtures.find(m => m.id === matchId);
  if (!match) return null;
  const homeTeam = resolveMatchTeam(match, 'home');
  const awayTeam = resolveMatchTeam(match, 'away');
  if (match.status === 'FINISHED' && match.score.home !== null) {
    if (match.score.home > match.score.away) return wantWinner ? homeTeam : awayTeam;
    if (match.score.away > match.score.home) return wantWinner ? awayTeam : homeTeam;
    return null;
  }
  const sim = simulations[String(matchId)];
  if (!sim || sim === 'DRAW') return null;
  if (sim === 'HOME') return wantWinner ? homeTeam : awayTeam;
  return wantWinner ? awayTeam : homeTeam;
}

function slotLabel(slot) {
  if (!slot) return null;
  if (slot.startsWith('win_') || slot.startsWith('lose_')) return null;
  const type = slot[0];
  const letters = slot.slice(2);
  if (type === 'w') return `1° Gr.${letters}`;
  if (type === 'r') return `2° Gr.${letters}`;
  return `3° (${letters.split('').join('/')})`;
}

function renderGroupCard(group) {
  const rows = group.table.map(row => `
    <tr${row._sim ? ' class="sim-row"' : ''}>
      <td class="pos">${row.position}</td>
      <td>
        <div class="team-cell">
          <img class="team-crest" src="${row.crest}" alt="${row.team}" onerror="this.style.display='none'">
          ${row.team}
        </div>
      </td>
      <td>${row.played}</td>
      <td>${row.won}</td>
      <td>${row.draw}</td>
      <td>${row.lost}</td>
      <td>${row.gf}</td>
      <td>${row.ga}</td>
      <td>${row.gd > 0 ? '+' + row.gd : row.gd}</td>
      <td><strong class="${row._sim ? 'sim-pts' : ''}">${row.points}</strong></td>
    </tr>
  `).join('');

  const simBadge = group._hasSim ? '<span class="sim-badge">SIM</span>' : '';

  return `
    <div class="group-card">
      <h3>${group.group.replace('Group ', 'GRUPO ')}${simBadge}</h3>
      <div class="table-scroll">
        <table class="group-table">
          <thead>
            <tr>
              <th>#</th><th class="col-team">Equipo</th>
              <th>PJ</th><th>G</th><th>E</th><th>P</th>
              <th>GF</th><th>GC</th><th>DG</th><th>PTS</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

// --- FIXTURES ---
function cleanStaleSimulations() {
  let changed = false;
  Object.keys(simulations).forEach(matchId => {
    const match = allFixtures.find(m => String(m.id) === matchId);
    if (!match) return;
    if (match.status === 'FINISHED') {
      delete simulations[matchId];
      changed = true;
      return;
    }
    // Group stage only: also clean when teams haven't been assigned yet
    if (match.stage === 'GROUP_STAGE') {
      const teamsKnown = match.homeTeam.name !== 'TBD' && match.awayTeam.name !== 'TBD';
      if (!teamsKnown) { delete simulations[matchId]; changed = true; }
    }
  });
  if (changed) localStorage.setItem('wc_simulations', JSON.stringify(simulations));
}

async function loadFixtures() {
  const container = document.getElementById('fixtures-container');
  try {
    allFixtures = await fetchFixtures();
    cleanStaleSimulations();
    renderFixtureFilters();
    if (Object.keys(simulations).length) renderGroups(); // populates currentSimGroups first
    renderFixtures();
  } catch (e) {
    container.innerHTML = `<div class="error">Error cargando partidos: ${e.message}</div>`;
  }
}

function renderFixtureFilters() {
  const stages = ['ALL', ...new Set(allFixtures.map(m => m.stage))];
  const filtersEl = document.getElementById('fixtures-filters');
  filtersEl.innerHTML = stages.map(s => `
    <button class="filter-btn ${s === currentStageFilter ? 'active' : ''}" data-stage="${s}">
      ${s === 'ALL' ? 'Todos' : (STAGE_LABELS[s] || s)}
    </button>
  `).join('');

  filtersEl.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      currentStageFilter = btn.dataset.stage;
      filtersEl.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderFixtures();
    });
  });
}

function renderFixtures() {
  const container = document.getElementById('fixtures-container');
  const filtered = currentStageFilter === 'ALL'
    ? allFixtures
    : allFixtures.filter(m => m.stage === currentStageFilter);

  if (!filtered.length) {
    container.innerHTML = '<div class="loading">Sin partidos para este filtro.</div>';
    return;
  }

  const byDate = filtered.reduce((acc, match) => {
    const date = new Date(match.utcDate).toLocaleDateString('es-MX', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    });
    if (!acc[date]) acc[date] = [];
    acc[date].push(match);
    return acc;
  }, {});

  container.innerHTML = Object.entries(byDate).map(([date, matches]) => `
    <div class="matchday-group">
      <div class="matchday-label">${date}</div>
      ${matches.map(renderMatchCard).join('')}
    </div>
  `).join('');
}

function renderMatchCard(match) {
  const isLive = match.status === 'IN_PLAY' || match.status === 'PAUSED';
  const isFinished = match.status === 'FINISHED';
  const hasScore = match.score.home !== null;
  const sim = simulations[String(match.id)];

  // --- bracket projection ---
  const bracketSlot = KNOCKOUT_BRACKET[match.id];
  const projHome = bracketSlot ? getProjectedTeam(bracketSlot.home) : null;
  const projAway = bracketSlot ? getProjectedTeam(bracketSlot.away) : null;
  const isProjected = bracketSlot
    && (match.homeTeam.name === 'TBD' || !match.homeTeam.name)
    && (projHome || projAway);

  const homeName = (match.homeTeam.name && match.homeTeam.name !== 'TBD')
    ? match.homeTeam.name : (projHome ? projHome.team : 'TBD');
  const awayName = (match.awayTeam.name && match.awayTeam.name !== 'TBD')
    ? match.awayTeam.name : (projAway ? projAway.team : 'TBD');
  const homeCrest = match.homeTeam.crest || (projHome ? projHome.crest : '');
  const awayCrest = match.awayTeam.crest || (projAway ? projAway.crest : '');

  const isKnockout = match.stage !== 'GROUP_STAGE';
  const isSimulable = ['TIMED', 'SCHEDULED'].includes(match.status)
    && homeName !== 'TBD' && awayName !== 'TBD';

  const time = new Date(match.utcDate).toLocaleTimeString('es-MX', {
    hour: '2-digit', minute: '2-digit', timeZone: 'America/Mexico_City',
  });

  const simScore = !hasScore && sim
    ? (sim === 'HOME' ? '2 - 1' : sim === 'AWAY' ? '1 - 2' : '1 - 1')
    : null;

  const scoreDisplay = hasScore
    ? `<div class="score-value">${match.score.home} - ${match.score.away}</div>`
    : simScore
      ? `<div class="score-value sim-score">${simScore}</div>`
      : `<div class="score-value" style="color:#555">vs</div>`;

  const venueStr = match.venue ? ` · ${match.venue}` : '';

  const MX_VENUES = ['Estadio Azteca', 'Estadio BBVA', 'Estadio Akron'];
  const CA_VENUES = ['BMO Field', 'BC Place'];
  const hostClass = match.venue
    ? MX_VENUES.some(v => match.venue.includes(v)) ? 'host-mx'
    : CA_VENUES.some(v => match.venue.includes(v)) ? 'host-ca'
    : 'host-us'
    : '';

  const timeBadge = isLive
    ? `<div class="score-time live-badge">EN VIVO</div>`
    : `<div class="score-time">${time} CDT${venueStr}</div>`;

  const homeLabel = slotLabel(bracketSlot?.home);
  const awayLabel = slotLabel(bracketSlot?.away);
  const groupTag = match.group
    ? `<div class="match-group-tag">${match.group.replace('GROUP_', 'Grupo ')}</div>`
    : isProjected && homeLabel && awayLabel
      ? `<div class="match-group-tag proj-slot">${homeLabel} · ${awayLabel}</div>`
      : '';

  let homeClass = '';
  let awayClass = '';
  if (isFinished && hasScore) {
    if (match.score.home > match.score.away)      { homeClass = 'sim-winner'; awayClass = 'sim-loser'; }
    else if (match.score.away > match.score.home) { homeClass = 'sim-loser';  awayClass = 'sim-winner'; }
    else                                          { homeClass = 'sim-draw';   awayClass = 'sim-draw'; }
  } else if (sim) {
    homeClass = sim === 'HOME' ? 'sim-winner' : sim === 'DRAW' ? 'sim-draw' : 'sim-loser';
    awayClass = sim === 'AWAY' ? 'sim-winner' : sim === 'DRAW' ? 'sim-draw' : 'sim-loser';
  }

  const projClass = isProjected ? 'proj-team' : '';

  const fc = forecasts[String(match.id)];
  const homeProb = fc ? `<span class="sim-prob">${Math.round(fc.homeWin * 100)}%</span>` : '';
  const drawProb = fc && fc.draw !== null ? `<span class="sim-prob">${Math.round(fc.draw * 100)}%</span>` : '';
  const awayProb = fc ? `<span class="sim-prob">${Math.round(fc.awayWin * 100)}%</span>` : '';

  // Fila de comparación Modelo vs. Mercado (solo cuando hay datos de mercado)
  const mkt = fc && fc.market && fc.market.available ? fc.market : null;
  const marketRow = mkt ? (() => {
    const m = mkt.marketProb;
    const mdl = fc.model;
    const pct = v => v != null ? `${Math.round(v * 100)}%` : '—';
    return `
    <div class="odds-row">
      <span class="odds-label">🤖</span>
      <span class="odds-val">${pct(mdl.homeWin)}</span>
      ${!isKnockout ? `<span class="odds-val draw">${pct(mdl.draw)}</span>` : ''}
      <span class="odds-val">${pct(mdl.awayWin)}</span>
      <span class="odds-sep">|</span>
      <span class="odds-label market">📊</span>
      <span class="odds-val">${pct(m.homeWin)}</span>
      ${!isKnockout ? `<span class="odds-val draw">${pct(m.draw)}</span>` : ''}
      <span class="odds-val">${pct(m.awayWin)}</span>
      <span class="odds-books">${mkt.bookmakerCount} casas</span>
    </div>`;
  })() : '';

  const simBar = isSimulable ? `
    <div class="sim-bar">
      <button class="sim-btn ${sim === 'HOME' ? 'sim-active-home' : ''}" data-match-id="${match.id}" data-result="HOME">${homeName}${homeProb}</button>
      ${!isKnockout ? `<button class="sim-btn sim-draw-btn ${sim === 'DRAW' ? 'sim-active-draw' : ''}" data-match-id="${match.id}" data-result="DRAW">Empate${drawProb}</button>` : ''}
      <button class="sim-btn ${sim === 'AWAY' ? 'sim-active-away' : ''}" data-match-id="${match.id}" data-result="AWAY">${awayName}${awayProb}</button>
      <button class="forecast-btn ${fc ? 'forecast-loaded' : ''}" data-match-id="${match.id}" data-home="${homeName}" data-away="${awayName}" data-stage="${match.stage}" data-knockout="${isKnockout ? '1' : '0'}" title="Pronóstico IA">${fc ? '✓' : '⚡'}</button>
      ${marketRow}
    </div>
  ` : '';

  return `
    <div class="match-card ${isLive ? 'live' : ''} ${isProjected ? 'projected' : ''} ${hostClass}">
      <div class="match-team ${homeClass} ${projClass}">
        ${homeCrest ? `<img src="${homeCrest}" alt="${homeName}" width="24" height="24" onerror="this.style.display='none'">` : ''}
        ${homeName}
      </div>
      <div class="match-score">
        ${groupTag}
        ${scoreDisplay}
        ${timeBadge}
      </div>
      <div class="match-team away ${awayClass} ${projClass}">
        ${awayName}
        ${awayCrest ? `<img src="${awayCrest}" alt="${awayName}" width="24" height="24" onerror="this.style.display='none'">` : ''}
      </div>
      ${simBar}
    </div>
  `;
}

// --- AUTO REFRESH ---
function startRefreshCountdown() {
  let secs = REFRESH_INTERVAL / 1000;
  const el = document.getElementById('refresh-countdown');
  clearInterval(countdown);
  countdown = setInterval(() => {
    secs--;
    if (el) el.textContent = secs;
    if (secs <= 0) secs = REFRESH_INTERVAL / 1000;
  }, 1000);
}

async function refresh() {
  await Promise.all([loadGroups(), loadFixtures()]);
  // Both loads done: re-render fixtures so bracket projections use final currentSimGroups
  renderFixtures();
  startRefreshCountdown();
}

async function init() {
  document.getElementById('clear-sims-btn').addEventListener('click', clearAllSimulations);

  document.getElementById('fixtures-container').addEventListener('click', async e => {
    const simBtn = e.target.closest('.sim-btn');
    if (simBtn) { saveSimulation(simBtn.dataset.matchId, simBtn.dataset.result); return; }

    const fcBtn = e.target.closest('.forecast-btn');
    if (!fcBtn || fcBtn.disabled) return;

    const { matchId, home, away, stage } = fcBtn.dataset;
    const isKnockout = fcBtn.dataset.knockout === '1';
    fcBtn.disabled = true;
    fcBtn.textContent = '…';

    try {
      const data = await fetchMatchForecast(home, away, stage);
      const wc = data.withCrowd;
      const mkt = data.market;  // null si no hay datos de mercado

      // Usar probabilidades blended si hay mercado disponible, sino modelo solo
      const display = (mkt && mkt.available && mkt.blended)
        ? mkt.blended
        : { homeWin: wc.homeWin, draw: wc.draw, awayWin: wc.awayWin };

      forecasts[String(matchId)] = {
        homeWin: display.homeWin,
        draw:    display.draw,
        awayWin: display.awayWin,
        model:   { homeWin: wc.homeWin, draw: wc.draw, awayWin: wc.awayWin },
        market:  mkt,
      };

      const best = isKnockout
        ? (display.homeWin >= display.awayWin ? 'HOME' : 'AWAY')
        : (display.homeWin >= (display.draw ?? 0) && display.homeWin >= display.awayWin ? 'HOME'
            : display.awayWin > (display.draw ?? 0) ? 'AWAY' : 'DRAW');
      saveSimulation(matchId, best);
    } catch {
      fcBtn.disabled = false;
      fcBtn.textContent = '⚡';
    }
  });
  await refresh();
  setInterval(refresh, REFRESH_INTERVAL);
}

document.addEventListener('DOMContentLoaded', init);
