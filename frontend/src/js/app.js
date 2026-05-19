const REFRESH_INTERVAL = 60000; // 60 segundos

async function loadGroups() {
  try {
    const data = await fetchGroups();
    document.getElementById('groups-container').innerHTML = renderGroups(data);
  } catch (e) {
    console.error('Error cargando grupos:', e);
  }
}

async function loadFixtures() {
  try {
    const data = await fetchFixtures();
    document.getElementById('fixtures-container').innerHTML = renderFixtures(data);
  } catch (e) {
    console.error('Error cargando partidos:', e);
  }
}

function renderGroups(data) {
  return `<p>Grupos pendientes de implementación</p>`;
}

function renderFixtures(data) {
  return `<p>Partidos pendientes de implementación</p>`;
}

async function init() {
  await Promise.all([loadGroups(), loadFixtures()]);
  setInterval(() => Promise.all([loadGroups(), loadFixtures()]), REFRESH_INTERVAL);
}

document.addEventListener('DOMContentLoaded', init);
