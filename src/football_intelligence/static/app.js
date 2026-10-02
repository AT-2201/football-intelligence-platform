const state = { overview: null, matches: [], teams: [], players: [], scouts: [] };
const titles = { overview: 'League intelligence', matches: 'Match analysis', teams: 'Team analysis', players: 'Player analysis', scouting: 'Scouting workspace' };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const fmt = (value, digits = 0) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits });
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

async function api(path) {
  if (window.portfolioApi) {
    const snapshot = await window.portfolioApi(path);
    if (snapshot !== undefined) return snapshot;
  }
  const response = await fetch(path);
  if (!response.ok) throw new Error((await response.json()).detail || `Request failed (${response.status})`);
  return response.json();
}
function toast(message) { const el = $('#toast'); el.textContent = message; el.classList.add('show'); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove('show'), 3500); }
function loading(el) { el.innerHTML = '<div class="loading">Loading intelligence…</div>'; }

function navigate(page) {
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.page === page));
  $$('.page').forEach(item => item.classList.toggle('active', item.id === `page-${page}`));
  $('#section-label').textContent = page.toUpperCase(); $('#page-title').textContent = titles[page];
  history.replaceState(null, '', `#${page}`); window.scrollTo({top: 0, behavior: 'smooth'});
  if (page === 'matches' && !state.matches.length) loadMatches();
  if (page === 'teams' && !state.teams.length) loadTeams();
  if (page === 'players' && !state.players.length) loadPlayers();
  if (page === 'scouting' && !state.scouts.length) loadScouting();
}

async function loadOverview() {
  try {
    const [overview, standings] = await Promise.all([api('/api/v1/overview'), api('/api/v1/standings')]);
    state.overview = overview;
    const c = overview.coverage;
    const complete = c.matches === c.expected_matches;
    $('#coverage-chip').innerHTML = `<span class="pulse"></span><strong>${fmt(c.matches)} / ${fmt(c.expected_matches)} matches</strong>`;
    $('#coverage-chip').title = complete ? 'Full season loaded' : 'Partial dataset loaded';
    $('#competition-heading').textContent = `${overview.competition.name} ${overview.competition.season}`;
    const metrics = [
      ['Matches', c.matches, `${c.matches && c.matches < 4 ? '<1' : Math.round(100*c.matches/c.expected_matches)}% season coverage`],
      ['Players', c.players, 'With recorded minutes'], ['Events', c.events, 'Normalized actions'], ['Goals', c.goals, 'Loaded fixtures']
    ];
    $('#overview-metrics').innerHTML = metrics.map(([label,value,meta]) => `<article class="metric-card"><span class="metric-label">${label}</span><strong class="metric-value">${fmt(value)}</strong><span class="metric-meta">${meta}</span></article>`).join('');
    $('#standings-body').innerHTML = standings.map(row => `<tr><td>${row.position}</td><td><strong>${esc(row.team_name)}</strong></td><td>${row.played}</td><td>${row.won}</td><td>${row.drawn}</td><td>${row.lost}</td><td>${row.goal_difference > 0 ? '+' : ''}${row.goal_difference}</td><td>${row.points}</td></tr>`).join('') || '<tr><td colspan="8">Run transformations to populate the table.</td></tr>';
    $('#top-scorers').innerHTML = overview.top_scorers.map((row,i) => `<button class="leader-row" data-player="${row.player_id}"><span class="rank">${String(i+1).padStart(2,'0')}</span><span><strong>${esc(row.player_name)}</strong><small>${esc(row.team_name)}</small></span><span class="leader-score">${row.goals}</span></button>`).join('') || '<div class="loading">No player totals yet.</div>';
    $$('#top-scorers [data-player]').forEach(el => el.onclick = () => { navigate('players'); setTimeout(() => openPlayer(el.dataset.player), 100); });
  } catch (error) { toast(error.message); }
}

async function loadMatches() {
  const list = $('#match-list'); loading(list);
  try { state.matches = await api('/api/v1/matches?limit=500'); renderMatches(); }
  catch (error) { list.innerHTML = ''; toast(error.message); }
}
function renderMatches() {
  const query = $('#match-search').value.trim().toLowerCase();
  const rows = state.matches.filter(m => `${m.home_team} ${m.away_team}`.toLowerCase().includes(query));
  $('#match-count').textContent = `${rows.length} fixture${rows.length === 1 ? '' : 's'}`;
  $('#match-list').innerHTML = rows.map(m => `<button class="match-row" data-match="${m.match_id}"><span class="match-date">MATCHWEEK ${m.match_week ?? '—'} · ${m.date}</span><span class="fixture"><span>${esc(m.home_team)}</span><strong class="score">${m.home_score}–${m.away_score}</strong><span>${esc(m.away_team)}</span></span></button>`).join('') || '<div class="loading">No matching fixtures.</div>';
  $$('#match-list [data-match]').forEach(el => el.onclick = () => openMatch(el.dataset.match));
}
async function openMatch(id) {
  $$('#match-list .match-row').forEach(el => el.classList.toggle('selected', el.dataset.match === String(id)));
  const detail = $('#match-detail'); loading(detail);
  try {
    const [match, shots, players] = await Promise.all([api(`/api/v1/matches/${id}`), api(`/api/v1/matches/${id}/events?event_type=Shot`), api(`/api/v1/matches/${id}/players`)]);
    const fixture = state.matches.find(m => m.match_id === Number(id)); const [home, away] = match.team_stats;
    const comp = (label, a, b, digits=0) => { const total = Number(a)+Number(b) || 1; return `<div class="stat-line"><strong>${fmt(a,digits)}</strong><div class="bar-track"><div class="bar" style="width:${100*Number(a)/total}%"></div></div><span>${label}</span><div class="bar-track"><div class="bar away" style="width:${100*Number(b)/total}%"></div></div><strong>${fmt(b,digits)}</strong></div>`; };
    detail.innerHTML = `<p class="section-kicker">MATCHWEEK ${fixture?.match_week ?? '—'} · ${fixture?.date ?? ''}</p><h3 class="detail-title">${esc(fixture?.home_team)} vs ${esc(fixture?.away_team)}</h3><p class="detail-subtitle">Match performance report</p><div class="comparison"><div><span>${esc(fixture?.home_team)}</span><strong>${match.home_score}</strong></div><span class="versus">FULL TIME</span><div><span>${esc(fixture?.away_team)}</span><strong>${match.away_score}</strong></div></div>${home && away ? `<div class="stat-compare">${comp('xG',home.xg,away.xg,2)}${comp('Shots',home.shots,away.shots)}${comp('Passes',home.passes,away.passes)}${comp('Possession',home.possession_pct,away.possession_pct,1)}</div>` : '<div class="loading">Run transformations for team comparisons.</div>'}<div class="shot-map"><div class="pitch">${shots.map(s => `<span class="shot ${s.team_id===match.away_team_id?'away':''} ${s.outcome==='Goal'?'goal':''}" style="left:${100*(s.x||0)/120}%;top:${100*(s.y||0)/80}%" title="${fmt(s.xg,2)} xG"></span>`).join('')}</div></div><div class="mini-table"><h4>Player output</h4><div class="table-wrap"><table><thead><tr><th>Player</th><th>Min</th><th>Shots</th><th>xG</th><th>Pass</th></tr></thead><tbody>${players.slice(0,14).map(p => `<tr><td>${esc(p.player_name)}</td><td>${fmt(p.minutes)}</td><td>${p.shots}</td><td>${fmt(p.xg,2)}</td><td>${p.completed_passes}/${p.passes}</td></tr>`).join('')}</tbody></table></div></div>`;
  } catch (error) { toast(error.message); detail.innerHTML = '<div class="empty-state"><h3>Unable to load match</h3></div>'; }
}

async function loadTeams() {
  const grid = $('#team-grid'); loading(grid);
  try { state.teams = await api('/api/v1/teams'); grid.innerHTML = state.teams.map(t => `<article class="team-card"><p class="section-kicker">${t.matches} MATCHES</p><h3>${esc(t.team_name)}</h3><div class="team-stats"><div class="team-stat"><span>Goals</span><strong>${t.goals}</strong></div><div class="team-stat"><span>xG</span><strong>${fmt(t.xg,1)}</strong></div><div class="team-stat"><span>Poss.</span><strong>${fmt(t.avg_possession_pct,1)}%</strong></div></div></article>`).join('') || '<div class="loading">Run transformations to populate club profiles.</div>'; }
  catch (error) { grid.innerHTML=''; toast(error.message); }
}

async function loadPlayers() {
  const list=$('#player-list'); loading(list);
  try { state.players = await api(`/api/v1/players?limit=500&min_minutes=${Number($('#player-minutes').value)||0}`); renderPlayers(); }
  catch(error) { list.innerHTML=''; toast(error.message); }
}
function renderPlayers() {
  const q=$('#player-search').value.trim().toLowerCase(); const rows=state.players.filter(p => `${p.player_name} ${p.team_name}`.toLowerCase().includes(q));
  $('#player-list').innerHTML=rows.map(p=>`<button class="data-row" data-player="${p.player_id}"><span><strong>${esc(p.player_name)}</strong><small>${esc(p.team_name)} · ${fmt(p.minutes)} min</small></span><span class="data-number">${p.goals}<small>GOALS</small></span></button>`).join('')||'<div class="loading">No players match these filters.</div>';
  $$('#player-list [data-player]').forEach(el=>el.onclick=()=>openPlayer(el.dataset.player));
}
async function openPlayer(id) {
  if (!state.players.length) await loadPlayers();
  $$('#player-list .data-row').forEach(el=>el.classList.toggle('selected',el.dataset.player===String(id)));
  const detail=$('#player-detail'); loading(detail);
  try { const [p,logs]=await Promise.all([api(`/api/v1/players/${id}`),api(`/api/v1/players/${id}/matches`)]); const keys=[['goals','Goals'],['shots','Shots'],['xg','xG'],['passes','Passes'],['carries','Carries'],['pressures','Pressures'],['tackles','Tackles'],['interceptions','Interceptions']]; detail.innerHTML=`<p class="section-kicker">${esc(p.team_name)}</p><h3 class="detail-title">${esc(p.player_name)}</h3><p class="detail-subtitle">${p.appearances} appearances · ${fmt(p.minutes)} minutes</p><div class="profile-grid">${keys.map(([key,label])=>`<div class="profile-stat"><span>${label} / 90</span><strong>${fmt(p.per_90[key],2)}</strong></div>`).join('')}</div><div class="mini-table"><h4>Recent match output</h4><div class="table-wrap"><table><thead><tr><th>Date</th><th>Min</th><th>G</th><th>xG</th><th>Pass</th></tr></thead><tbody>${logs.map(r=>`<tr><td>${r.date}</td><td>${fmt(r.minutes)}</td><td>${r.goals}</td><td>${fmt(r.xg,2)}</td><td>${r.passes}</td></tr>`).join('')}</tbody></table></div></div>`; }
  catch(error){toast(error.message);}
}

async function loadScouting() {
  const list=$('#scout-list'); loading(list); const profile=$('#scout-profile').value, minutes=Number($('#scout-minutes').value)||0, position=$('#scout-position').value.trim();
  try { state.scouts=await api(`/api/v1/scouting/players?profile=${encodeURIComponent(profile)}&min_minutes=${minutes}&position=${encodeURIComponent(position)}&limit=200`); list.innerHTML=state.scouts.map(p=>`<button class="data-row" data-scout="${p.player_id}"><span><strong>${esc(p.player_name)}</strong><small>${esc(p.team_name)} · ${esc(p.position)} · ${fmt(p.minutes)} min</small></span><span class="score-badge">${fmt(p.scouting_score)}</span></button>`).join('')||'<div class="loading">No qualified players. Lower the minimum minutes or broaden the position.</div>'; $$('#scout-list [data-scout]').forEach(el=>el.onclick=()=>openScout(el.dataset.scout)); }
  catch(error){list.innerHTML='';toast(error.message);}
}
async function openScout(id) {
  $$('#scout-list .data-row').forEach(el=>el.classList.toggle('selected',el.dataset.scout===String(id))); const p=state.scouts.find(x=>x.player_id===Number(id)); if(!p)return; const detail=$('#scout-detail'); const metrics=['goals','xg','shots','passes','carries','pressures','tackles','interceptions']; detail.innerHTML=`<p class="section-kicker">${esc(p.position)} · ${esc(p.team_name)}</p><h3 class="detail-title">${esc(p.player_name)}</h3><p class="detail-subtitle">League profile · ${fmt(p.minutes)} minutes</p><div class="percentile-list">${metrics.map(k=>`<div class="percentile-row"><span>${k}</span><div class="bar-track"><div class="bar" style="width:${p.percentiles[k]}%"></div></div><strong>${p.percentiles[k]}</strong></div>`).join('')}</div><div id="similar-players"><div class="loading">Finding similar players…</div></div>`;
  try { const data=await api(`/api/v1/scouting/players/${id}/similar?min_minutes=${Number($('#scout-minutes').value)||0}&limit=5`); $('#similar-players').innerHTML=`<h4 class="detail-section-title">Similar profiles</h4><div class="leader-list">${data.similar_players.map((s,i)=>`<div class="leader-row"><span class="rank">${String(i+1).padStart(2,'0')}</span><span><strong>${esc(s.player_name)}</strong><small>${esc(s.team_name)}</small></span><span class="leader-score">${fmt(s.similarity)}%</span></div>`).join('')||'<p class="muted">No same-position comparisons meet the minutes threshold.</p>'}</div>`; } catch(error){toast(error.message);}
}

$$('.nav-item').forEach(item=>item.onclick=()=>navigate(item.dataset.page));
$('#match-search').addEventListener('input',renderMatches);
$('#player-search').addEventListener('input',renderPlayers);
$('#player-minutes').addEventListener('change',loadPlayers);
$('#run-scout').addEventListener('click',loadScouting);
const initial=location.hash.slice(1); navigate(titles[initial]?initial:'overview'); loadOverview();
