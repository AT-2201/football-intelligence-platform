const state = { overview: null, matches: [], teams: [], players: [], scouts: [], selectedScoutId: null, comparePool: [], comparisonIds: [], comparison: null };
const titles = { overview: 'League intelligence', matches: 'Match analysis', teams: 'Team analysis', players: 'Player analysis', scouting: 'Player similarity explorer', compare: 'Player comparison' };
const comparisonMetrics = [
  ['attacking','goals','Goals',0], ['attacking','xg','xG',2], ['attacking','shots','Shots',0],
  ['possession','passes','Passes',0], ['possession','carries','Carries',0],
  ['defending','pressures','Pressures',0], ['defending','tackles','Tackles',0], ['defending','interceptions','Interceptions',0]
];
const playerColors = ['#a8ff35','#53a8ff','#ffbe55','#b78cff','#4dded2'];
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
  if (page === 'compare' && !state.comparePool.length) loadComparisonWorkspace();
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
  const list=$('#scout-list'); loading(list); const minutes=Number($('#scout-minutes').value)||0, search=$('#scout-player').value.trim(), position=$('#scout-position').value.trim();
  try { state.scouts=await api(`/api/v1/scouting/players?min_minutes=${minutes}&search=${encodeURIComponent(search)}&position=${encodeURIComponent(position)}&limit=200`); list.innerHTML=state.scouts.map(p=>`<button class="data-row" data-scout="${p.player_id}"><span><strong>${esc(p.player_name)}</strong><small>${esc(p.team_name)} · ${esc(p.position)} · ${fmt(p.minutes)} min</small></span><span class="data-number">${fmt(p.appearances)}<small>APPS</small></span></button>`).join('')||'<div class="loading">No players match these filters. Adjust the player, minimum minutes or position search.</div>'; $$('#scout-list [data-scout]').forEach(el=>el.onclick=()=>openScout(el.dataset.scout)); }
  catch(error){list.innerHTML='';toast(error.message);}
}
async function openScout(id) {
  state.selectedScoutId=Number(id);
  $$('#scout-list .data-row').forEach(el=>el.classList.toggle('selected',el.dataset.scout===String(id))); const p=state.scouts.find(x=>x.player_id===Number(id)); if(!p)return; const detail=$('#scout-detail'); const metrics=[['goals','Goals'],['xg','xG'],['shots','Shots'],['passes','Passes'],['carries','Carries'],['pressures','Pressures'],['tackles','Tackles'],['interceptions','Interceptions']]; detail.innerHTML=`<p class="section-kicker">REFERENCE PLAYER · ${esc(p.position)}</p><h3 class="detail-title">${esc(p.player_name)}</h3><p class="detail-subtitle">${esc(p.team_name)} · ${fmt(p.appearances)} appearances · ${fmt(p.minutes)} minutes</p><h4 class="detail-section-title">Season output</h4><div class="scout-stat-grid">${metrics.map(([key,label])=>`<div class="scout-stat"><span>${label}</span><strong>${fmt(p.totals[key],key==='xg'?2:0)}</strong><small>${fmt(p.per_90[key],2)} / 90</small></div>`).join('')}</div><div id="similar-players"><div class="loading">Finding and explaining similar players…</div></div>`;
  try {
    const data=await api(`/api/v1/scouting/players/${id}/similar?min_minutes=${Number($('#scout-minutes').value)||0}&limit=5`);
    const cards=data.similar_players.map((candidate,index)=>{
      const reasons=candidate.match_reasons.map(reason=>`<span class="match-reason"><strong>${esc(metricLabel(reason.metric))}</strong>${fmt(reason.target,2)} → ${fmt(reason.candidate,2)} /90</span>`).join('');
      const tradeoffs=candidate.trade_offs.map(item=>{const direction=item.difference>0?'more':'less';return `<li><strong>${fmt(Math.abs(item.difference),2)} ${direction}</strong> ${esc(metricLabel(item.metric))} per 90</li>`;}).join('');
      return `<article class="replacement-card"><div class="replacement-rank">${String(index+1).padStart(2,'0')}</div><div class="replacement-main"><div class="replacement-heading"><div><h5>${esc(candidate.player_name)}</h5><p>${esc(candidate.team_name)} · ${esc(candidate.position)}</p></div><div class="similarity-score"><strong>${fmt(candidate.similarity,1)}%</strong><span>PROFILE MATCH</span></div></div><div class="reason-block"><span class="reason-label">Closest traits</span><div class="reason-chips">${reasons}</div></div><div class="tradeoff-row"><div><span class="reason-label">Key trade-offs</span><ul>${tradeoffs}</ul></div><button class="secondary-button compare-replacement" data-compare-replacement="${candidate.player_id}">Compare players</button></div></div></article>`;
    }).join('');
    $('#similar-players').innerHTML=`<div class="similarity-intro"><div><p class="section-kicker">SIMILAR PLAYERS · ${esc(data.position_group)}</p><h4>Why these players match</h4><p>Closest statistical profiles across eight normalized season metrics.</p></div><span>All metrics compared per 90</span></div><div class="replacement-list">${cards||'<p class="muted">No players in this position family meet the minutes threshold.</p>'}</div><p class="method-note">${esc(data.methodology)} Similarity describes statistical profile—not quality, value or tactical fit.</p>`;
    $$('[data-compare-replacement]').forEach(button=>button.onclick=()=>{state.comparisonIds=[state.selectedScoutId,Number(button.dataset.compareReplacement)];navigate('compare');if(state.comparePool.length){renderComparisonSelection();renderComparison();}});
  } catch(error){toast(error.message);}
}

async function loadComparisonWorkspace() {
  try {
    state.comparePool = await api('/api/v1/scouting/players?min_minutes=450&limit=1000');
    state.comparePool.sort((a,b)=>a.player_name.localeCompare(b.player_name));
    renderComparisonSelection();
    if(state.comparisonIds.length>=2)renderComparison();
  } catch(error) { toast(error.message); }
}

function renderComparisonSearch() {
  const query=$('#compare-search').value.trim().toLowerCase();
  const results=$('#compare-results');
  if (query.length < 2) { results.innerHTML=''; return; }
  const matches=state.comparePool.filter(player => !state.comparisonIds.includes(player.player_id) && `${player.player_name} ${player.team_name} ${player.position}`.toLowerCase().includes(query)).slice(0,6);
  results.innerHTML=matches.map(player=>`<button class="compare-result" data-compare-add="${player.player_id}"><span><strong>${esc(player.player_name)}</strong><small>${esc(player.team_name)} · ${esc(player.position)}</small></span><em>ADD</em></button>`).join('')||'<p class="muted">No eligible players match that search.</p>';
  $$('[data-compare-add]').forEach(button=>button.onclick=()=>addComparisonPlayer(Number(button.dataset.compareAdd)));
}

function addComparisonPlayer(playerId) {
  if (state.comparisonIds.includes(playerId)) return;
  if (state.comparisonIds.length >= 5) { toast('A comparison can include up to five players.'); return; }
  state.comparisonIds.push(playerId);
  $('#compare-search').value=''; $('#compare-results').innerHTML='';
  renderComparisonSelection(); renderComparison();
}

function removeComparisonPlayer(playerId) {
  state.comparisonIds=state.comparisonIds.filter(id=>id!==playerId);
  renderComparisonSelection(); renderComparison();
}

function renderComparisonSelection() {
  const selected=state.comparisonIds.map(id=>state.comparePool.find(player=>player.player_id===id)).filter(Boolean);
  $('#compare-selection').innerHTML=selected.map((player,index)=>`<span class="compare-chip" style="--player-color:${playerColors[index]}"><i></i>${esc(player.player_name)}<button type="button" data-compare-remove="${player.player_id}" aria-label="Remove ${esc(player.player_name)}">×</button></span>`).join('');
  $$('[data-compare-remove]').forEach(button=>button.onclick=()=>removeComparisonPlayer(Number(button.dataset.compareRemove)));
  $('#compare-guidance').textContent=selected.length<2?`Select ${2-selected.length} more player${selected.length===1?'':'s'} to begin. You can compare up to five.`:`${selected.length} players selected · ${5-selected.length} spaces remaining`;
  const download=$('#download-comparison');
  download.classList.toggle('disabled',selected.length<2);
  download.setAttribute('aria-disabled',String(selected.length<2));
  if(selected.length<2){download.href='#';download.removeAttribute('download');}
}

function radarSvg(players) {
  const size=400, center=200, radius=142, axes=comparisonMetrics.length;
  const point=(index,value,extra=0)=>{const angle=-Math.PI/2+2*Math.PI*index/axes, distance=radius*value+extra; return [center+Math.cos(angle)*distance,center+Math.sin(angle)*distance];};
  const points=value=>comparisonMetrics.map((_,index)=>point(index,value).join(',')).join(' ');
  const grids=[.25,.5,.75,1].map(value=>`<polygon class="radar-grid" points="${points(value)}"></polygon>`).join('');
  const axisLines=comparisonMetrics.map((_,index)=>{const [x,y]=point(index,1);return `<line class="radar-axis" x1="${center}" y1="${center}" x2="${x}" y2="${y}"></line>`;}).join('');
  const labels=comparisonMetrics.map(([,key,label],index)=>{const [x,y]=point(index,1,28);return `<text class="radar-label" x="${x}" y="${y}">${label}</text>`;}).join('');
  const shapes=players.map((player,index)=>`<polygon class="radar-player" style="--player-color:${playerColors[index]}" points="${comparisonMetrics.map(([,key],axis)=>point(axis,player.relative_profile[key]/100).join(',')).join(' ')}"></polygon>`).join('');
  return `<svg class="radar-chart" viewBox="0 0 ${size} ${size}" role="img" aria-label="League-relative player profile comparison">${grids}${axisLines}${shapes}${labels}</svg>`;
}

function metricLabel(key) { return comparisonMetrics.find(([,metric])=>metric===key)?.[2]||key; }

async function renderComparison() {
  const container=$('#comparison-content');
  if (state.comparisonIds.length<2) { state.comparison=null; container.innerHTML='<div class="empty-state comparison-empty"><span class="empty-glyph">⇄</span><h3>Build a comparison</h3><p>Add two to five players to inspect their production, profile shape and similarity.</p></div>'; return; }
  loading(container);
  try {
    const query=state.comparisonIds.map(id=>`player_ids=${id}`).join('&');
    state.comparison=await api(`/api/v1/scouting/compare?${query}`);
    const players=state.comparison.players;
    const legend=players.map((player,index)=>`<span class="legend-item" style="--player-color:${playerColors[index]}"><i class="legend-dot"></i>${esc(player.player_name)}</span>`).join('');
    let lastCategory='';
    const rows=comparisonMetrics.map(([category,key,label,digits])=>{const categoryRow=category!==lastCategory?`<tr class="category-row"><td colspan="${players.length+1}">${category}</td></tr>`:'';lastCategory=category;return `${categoryRow}<tr><td>${label}</td>${players.map(player=>`<td><strong>${fmt(player.totals[key],digits)}</strong><small>${fmt(player.per_90[key],2)} / 90</small></td>`).join('')}</tr>`;}).join('');
    const insights=players.map((player,index)=>`<article class="insight-card" style="--player-color:${playerColors[index]}"><h4>${esc(player.player_name)}</h4><small>${esc(player.team_name)} · ${esc(player.position)}</small><div class="insight-columns"><div><h5>Statistical strengths</h5><div class="insight-list">${player.strengths.map(key=>`<span class="insight-item"><span>${metricLabel(key)}</span><strong>${fmt(player.per_90[key],2)}/90</strong></span>`).join('')}</div></div><div><h5>Lower relative output</h5><div class="insight-list">${player.development_areas.map(key=>`<span class="insight-item"><span>${metricLabel(key)}</span><strong>${fmt(player.per_90[key],2)}/90</strong></span>`).join('')}</div></div></div></article>`).join('');
    const names=Object.fromEntries(players.map(player=>[player.player_id,player.player_name]));
    const similarities=state.comparison.similarities.map(pair=>`<div class="similarity-card"><span>${esc(names[pair.player_a_id])} ↔ ${esc(names[pair.player_b_id])}</span><strong>${fmt(pair.similarity,1)}% similar</strong></div>`).join('');
    container.innerHTML=`<div class="comparison-layout"><div class="comparison-summary"><div><p class="section-kicker">COMPARISON SET</p><h3>${players.length} player profiles</h3></div><div class="comparison-legend">${legend}</div></div><div class="comparison-visuals"><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">PROFILE SHAPE</p><h3>League-relative radar</h3></div><span class="muted">Per 90 · min. 450 benchmark</span></div><div class="radar-wrap">${radarSvg(players)}</div></article><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">OUTPUT</p><h3>Totals and per-90 rates</h3></div><span class="muted">Premier League 2015/16</span></div><div class="table-wrap"><table class="comparison-table"><thead><tr><th>Metric</th>${players.map((player,index)=>`<th style="color:${playerColors[index]}">${esc(player.player_name)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></article></div><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">INTERPRETATION</p><h3>Strengths and development areas</h3></div><span class="muted">Relative to league-qualified players</span></div><div class="insight-grid">${insights}</div></article><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">STYLE MATCH</p><h3>Pairwise similarity</h3></div><span class="muted">Standardized eight-metric profile</span></div><div class="similarity-grid">${similarities}</div></article></div>`;
    prepareComparisonReport();
  } catch(error) { container.innerHTML='<div class="empty-state comparison-empty"><h3>Unable to build comparison</h3></div>'; toast(error.message); }
}

function prepareComparisonReport() {
  if (!state.comparison) return;
  const players=state.comparison.players;
  const headers=['Player','Club','Position','Appearances','Minutes',...comparisonMetrics.flatMap(([,key,label])=>[`${label} total`,`${label} per 90`]),'Statistical strengths','Lower relative output'];
  const quote=value=>`"${String(value??'').replaceAll('"','""')}"`;
  const rows=players.map(player=>[player.player_name,player.team_name,player.position,player.appearances,player.minutes,...comparisonMetrics.flatMap(([,key])=>[player.totals[key],player.per_90[key]]),player.strengths.map(metricLabel).join('; '),player.development_areas.map(metricLabel).join('; ')]);
  const csv=[headers,...rows].map(row=>row.map(quote).join(',')).join('\n');
  const link=$('#download-comparison');
  link.href=`data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  link.download='premier-league-2015-16-player-comparison.csv';
}

$$('.nav-item').forEach(item=>item.onclick=()=>navigate(item.dataset.page));
$('#match-search').addEventListener('input',renderMatches);
$('#player-search').addEventListener('input',renderPlayers);
$('#player-minutes').addEventListener('change',loadPlayers);
$('#run-scout').addEventListener('click',loadScouting);
['#scout-player','#scout-position'].forEach(selector=>$(selector).addEventListener('keydown',event=>{if(event.key==='Enter')loadScouting();}));
$('#compare-search').addEventListener('input',renderComparisonSearch);
$('#download-comparison').addEventListener('click',event=>{if(event.currentTarget.classList.contains('disabled'))event.preventDefault();});
const initial=location.hash.slice(1); navigate(titles[initial]?initial:'overview'); loadOverview();
