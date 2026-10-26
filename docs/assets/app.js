const state = { overview: null, matches: [], teams: [], players: [], scouts: [], selectedScoutId: null, replacementData: null, shortlistIds: [], comparePool: [], comparisonIds: [], comparison: null };
const titles = { overview: 'League intelligence', matches: 'Match analysis', teams: 'Team analysis', players: 'Player analysis', scouting: 'Player replacement finder', compare: 'Advanced player comparison' };
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
  state.shortlistIds=[];
  state.replacementData=null;
  $$('#scout-list .data-row').forEach(el=>el.classList.toggle('selected',el.dataset.scout===String(id))); const p=state.scouts.find(x=>x.player_id===Number(id)); if(!p)return; const detail=$('#scout-detail'); const metrics=[['goals','Goals'],['xg','xG'],['shots','Shots'],['passes','Passes'],['carries','Carries'],['pressures','Pressures'],['tackles','Tackles'],['interceptions','Interceptions']]; detail.innerHTML=`<p class="section-kicker">REFERENCE PLAYER · ${esc(p.position)}</p><h3 class="detail-title">${esc(p.player_name)}</h3><p class="detail-subtitle">${esc(p.team_name)} · ${fmt(p.appearances)} appearances · ${fmt(p.minutes)} minutes</p><h4 class="detail-section-title">Season output</h4><div class="scout-stat-grid">${metrics.map(([key,label])=>`<div class="scout-stat"><span>${label}</span><strong>${fmt(p.totals[key],key==='xg'?2:0)}</strong><small>${fmt(p.per_90[key],2)} / 90</small></div>`).join('')}</div><div id="similar-players"><div class="loading">Screening replacement candidates…</div></div>`;
  try {
    const data=await api(`/api/v1/scouting/players/${id}/replacements?min_minutes=${Number($('#scout-minutes').value)||0}&exclude_same_team=${$('#scout-exclude-club').checked}&limit=8`);
    state.replacementData=data;
    const cards=data.replacement_candidates.map((candidate,index)=>{
      const reasons=candidate.match_reasons.map(reason=>`<span class="match-reason"><strong>${esc(metricLabel(reason.metric))}</strong>${fmt(reason.target,2)} → ${fmt(reason.candidate,2)} /90</span>`).join('');
      const tradeoffs=candidate.trade_offs.map(item=>{const direction=item.difference>0?'more':'less';return `<li><strong>${fmt(Math.abs(item.difference),2)} ${direction}</strong> ${esc(metricLabel(item.metric))} per 90</li>`;}).join('');
      return `<article class="replacement-card" data-candidate-card="${candidate.player_id}"><div class="replacement-rank">${String(index+1).padStart(2,'0')}</div><div class="replacement-main"><div class="replacement-heading"><div><h5>${esc(candidate.player_name)}</h5><p>${esc(candidate.team_name)} · ${esc(candidate.position)} · ${fmt(candidate.minutes)} min</p></div><div class="similarity-score"><strong>${fmt(candidate.similarity,1)}%</strong><span>SIMILARITY</span></div></div><div class="reason-block"><span class="reason-label">Why this player matches</span><div class="reason-chips">${reasons}</div></div><div class="tradeoff-row"><div><span class="reason-label">Key trade-offs</span><ul>${tradeoffs}</ul></div><div class="replacement-actions"><button class="secondary-button shortlist-button" data-shortlist="${candidate.player_id}">Add to shortlist</button><button class="secondary-button compare-replacement" data-compare-replacement="${candidate.player_id}">Compare</button></div></div></div></article>`;
    }).join('');
    $('#similar-players').innerHTML=`<div class="similarity-intro"><div><p class="section-kicker">REPLACEMENT POOL · ${esc(data.position_group)}</p><h4>Ranked replacement candidates</h4><p>Position-aware statistical matches with the evidence and trade-offs shown.</p></div><span>${fmt(data.screening.eligible_candidates)} eligible · all metrics per 90</span></div><div class="shortlist-toolbar"><div><strong id="shortlist-count">0 shortlisted</strong><span>Select candidates for a meeting-ready comparison.</span></div><button class="primary-button disabled" id="compare-shortlist" type="button" disabled>Compare shortlist</button></div><div class="replacement-list">${cards||'<p class="muted">No players in this position family meet the current screening filters.</p>'}</div><p class="method-note">${esc(data.methodology)} Similarity describes statistical profile—not quality, value or tactical fit.</p>`;
    $$('[data-compare-replacement]').forEach(button=>button.onclick=()=>{state.comparisonIds=[state.selectedScoutId,Number(button.dataset.compareReplacement)];navigate('compare');if(state.comparePool.length){renderComparisonSelection();renderComparison();}});
    $$('[data-shortlist]').forEach(button=>button.onclick=()=>toggleShortlist(Number(button.dataset.shortlist)));
    $('#compare-shortlist').onclick=compareShortlist;
  } catch(error){toast(error.message);}
}

function toggleShortlist(playerId) {
  if (state.shortlistIds.includes(playerId)) state.shortlistIds=state.shortlistIds.filter(id=>id!==playerId);
  else if (state.shortlistIds.length<4) state.shortlistIds.push(playerId);
  else { toast('Shortlist up to four candidates alongside the reference player.'); return; }
  $$('[data-shortlist]').forEach(button=>{
    const selected=state.shortlistIds.includes(Number(button.dataset.shortlist));
    button.classList.toggle('selected',selected);
    button.textContent=selected?'Shortlisted':'Add to shortlist';
    button.closest('.replacement-card')?.classList.toggle('shortlisted',selected);
  });
  const count=$('#shortlist-count');
  if(count)count.textContent=`${state.shortlistIds.length} shortlisted`;
  const compare=$('#compare-shortlist');
  if(compare){compare.disabled=!state.shortlistIds.length;compare.classList.toggle('disabled',!state.shortlistIds.length);}
}

function compareShortlist() {
  if (!state.shortlistIds.length) return;
  state.comparisonIds=[state.selectedScoutId,...state.shortlistIds];
  navigate('compare');
  if(state.comparePool.length){renderComparisonSelection();renderComparison();}
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

function directMetricBars(players) {
  return `<div class="metric-bar-grid">${comparisonMetrics.map(([,key,label])=>{
    const maximum=Math.max(...players.map(player=>Number(player.per_90[key])||0),0.01);
    const rows=players.map((player,index)=>{
      const value=Number(player.per_90[key])||0;
      return `<div class="metric-bar-row" style="--player-color:${playerColors[index]}"><div class="metric-bar-meta"><span>${esc(player.player_name)}</span><strong>${fmt(value,2)}</strong></div><div class="metric-bar-track"><span style="width:${100*value/maximum}%"></span></div></div>`;
    }).join('');
    return `<article class="metric-bar-card"><div class="metric-bar-title"><h4>${label}</h4><span>per 90</span></div>${rows}</article>`;
  }).join('')}</div>`;
}

function workloadCards(players) {
  return `<div class="workload-grid">${players.map((player,index)=>`<article class="workload-card" style="--player-color:${playerColors[index]}"><span class="workload-dot"></span><div><h4>${esc(player.player_name)}</h4><p>${esc(player.team_name)} · ${esc(player.position)}</p></div><dl><div><dt>Minutes</dt><dd>${fmt(player.minutes)}</dd></div><div><dt>Appearances</dt><dd>${fmt(player.appearances)}</dd></div></dl></article>`).join('')}</div>`;
}

function selectedLeaders(players, metricLeaders) {
  const names=Object.fromEntries(players.map(player=>[player.player_id,player.player_name]));
  return `<div class="leader-chip-grid">${comparisonMetrics.map(([,key,label])=>{
    const leader=metricLeaders[key];
    const leaders=leader.player_ids.map(id=>names[id]).filter(Boolean).join(' & ');
    return `<div class="leader-chip"><span>${label} / 90</span><strong>${esc(leaders)}</strong><em>${fmt(leader.value,2)}</em></div>`;
  }).join('')}</div>`;
}

function metricLabel(key) { return comparisonMetrics.find(([,metric])=>metric===key)?.[2]||key; }

async function renderComparison() {
  const container=$('#comparison-content');
  if (state.comparisonIds.length<2) { state.comparison=null; container.innerHTML='<div class="empty-state comparison-empty"><span class="empty-glyph">⇄</span><h3>Build a comparison</h3><p>Add two to five players to inspect their production, workload, metric differences and similarity.</p></div>'; return; }
  loading(container);
  try {
    const query=state.comparisonIds.map(id=>`player_ids=${id}`).join('&');
    state.comparison=await api(`/api/v1/scouting/compare?${query}`);
    const players=state.comparison.players;
    const legend=players.map((player,index)=>`<span class="legend-item" style="--player-color:${playerColors[index]}"><i class="legend-dot"></i>${esc(player.player_name)}</span>`).join('');
    let lastCategory='';
    const rows=comparisonMetrics.map(([category,key,label,digits])=>{const categoryRow=category!==lastCategory?`<tr class="category-row"><td colspan="${players.length+1}">${category}</td></tr>`:'';lastCategory=category;return `${categoryRow}<tr><td>${label}</td>${players.map(player=>`<td><strong>${fmt(player.totals[key],digits)}</strong><small>${fmt(player.per_90[key],2)} / 90</small></td>`).join('')}</tr>`;}).join('');
    const names=Object.fromEntries(players.map(player=>[player.player_id,player.player_name]));
    const similarities=state.comparison.similarities.map(pair=>`<div class="similarity-card"><span>${esc(names[pair.player_a_id])} ↔ ${esc(names[pair.player_b_id])}</span><strong>${fmt(pair.similarity,1)}% similar</strong></div>`).join('');
    container.innerHTML=`<div class="comparison-layout"><div class="comparison-summary"><div><p class="section-kicker">COMPARISON SET</p><h3>${players.length} player profiles</h3></div><div class="comparison-legend">${legend}</div></div><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">WORKLOAD</p><h3>Season availability</h3></div><span class="muted">Appearances and minutes</span></div>${workloadCards(players)}</article><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">VISUAL COMPARISON</p><h3>Actual per-90 output</h3></div><span class="muted">Bar length is relative only to this comparison set</span></div>${directMetricBars(players)}</article><div class="comparison-visuals direct-comparison-layout"><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">OUTPUT</p><h3>Totals and per-90 rates</h3></div><span class="muted">Premier League 2015/16</span></div><div class="table-wrap"><table class="comparison-table"><thead><tr><th>Metric</th>${players.map((player,index)=>`<th style="color:${playerColors[index]}">${esc(player.player_name)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></article><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">SELECTED LEADERS</p><h3>Who leads each metric?</h3></div><span class="muted">Highest actual per-90 value</span></div>${selectedLeaders(players,state.comparison.metric_leaders)}</article></div><article class="comparison-panel"><div class="comparison-panel-heading"><div><p class="section-kicker">PROFILE MATCH</p><h3>Pairwise similarity</h3></div><span class="muted">Standardized eight-metric profile</span></div><div class="similarity-grid">${similarities}</div><p class="method-note">Similarity measures statistical profile resemblance. It does not rank overall quality, value or tactical fit.</p></article></div>`;
    prepareComparisonReport();
  } catch(error) { container.innerHTML='<div class="empty-state comparison-empty"><h3>Unable to build comparison</h3></div>'; toast(error.message); }
}

function prepareComparisonReport() {
  if (!state.comparison) return;
  const players=state.comparison.players;
  const headers=['Player','Club','Position','Appearances','Minutes',...comparisonMetrics.flatMap(([,key,label])=>[`${label} total`,`${label} per 90`])];
  const quote=value=>`"${String(value??'').replaceAll('"','""')}"`;
  const rows=players.map(player=>[player.player_name,player.team_name,player.position,player.appearances,player.minutes,...comparisonMetrics.flatMap(([,key])=>[player.totals[key],player.per_90[key]])]);
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
$('#scout-exclude-club').addEventListener('change',()=>{if(state.selectedScoutId)openScout(state.selectedScoutId);});
$('#compare-search').addEventListener('input',renderComparisonSearch);
$('#download-comparison').addEventListener('click',event=>{if(event.currentTarget.classList.contains('disabled'))event.preventDefault();});
const initial=location.hash.slice(1); navigate(titles[initial]?initial:'overview'); loadOverview();
