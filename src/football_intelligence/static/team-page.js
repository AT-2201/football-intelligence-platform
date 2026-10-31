/* Team intelligence page: club selection, tactical summaries and spatial maps. */

function initTeamPageControls() {
  document.querySelector('#open-team-profile').addEventListener('click',()=>openTeam(Number(document.querySelector('#team-select').value)));
  document.querySelector('#team-select').addEventListener('change',event=>openTeam(Number(event.target.value)));
}

async function loadTeamsWorkspace() {
  const grid = $('#team-grid'); loading(grid);
  try {
    state.teams = await api('/api/v1/teams');
    state.teams.sort((a,b)=>a.team_name.localeCompare(b.team_name));
    $('#team-select').innerHTML=state.teams.map(team=>`<option value="${team.team_id}">${esc(team.team_name)}</option>`).join('');
    const preferred=state.teams.find(team=>team.team_name==='Leicester City')||state.teams[0];
    if(preferred)$('#team-select').value=String(preferred.team_id);
    grid.innerHTML = state.teams.map(t => `<button type="button" class="team-card team-card-button" data-team-profile="${t.team_id}"><div class="team-card-heading">${crest(t.team_name,'team-card-crest')}<div><p class="section-kicker">${t.matches} LEAGUE MATCHES</p><h3>${esc(t.team_name)}</h3></div><span class="open-arrow" aria-hidden="true">→</span></div><div class="team-stats"><div class="team-stat"><span>Goals scored</span><strong>${t.goals}</strong></div><div class="team-stat"><span>Expected goals</span><strong>${fmt(t.xg,1)}</strong></div><div class="team-stat"><span>Avg. possession</span><strong>${fmt(t.avg_possession_pct,1)}%</strong></div></div><span class="team-card-cta">View complete club analysis</span></button>`).join('') || '<div class="loading">Run transformations to populate club profiles.</div>';
    $$('[data-team-profile]').forEach(button=>button.onclick=()=>openTeam(Number(button.dataset.teamProfile)));
    const pending=state.pendingTeamName&&state.teams.find(team=>team.team_name===state.pendingTeamName);
    if(pending){state.pendingTeamName=null;await openTeam(pending.team_id);}
  } catch (error) { grid.innerHTML=''; toast(error.message); }
}

function teamMetric(label,value,context='') {
  return `<article class="club-metric"><span>${esc(label)}</span><strong>${value}</strong>${context?`<small>${esc(context)}</small>`:''}</article>`;
}

function resultPill(result) { return `<span class="result-pill result-${result.toLowerCase()}">${result}</span>`; }

function pitchLines() {
  return `<g class="pitch-lines"><rect x="1" y="1" width="118" height="78" rx="1"/><line x1="60" y1="1" x2="60" y2="79"/><circle cx="60" cy="40" r="10"/><circle cx="60" cy="40" r=".8"/><rect x="1" y="18" width="18" height="44"/><rect x="101" y="18" width="18" height="44"/><rect x="1" y="30" width="6" height="20"/><rect x="113" y="30" width="6" height="20"/><circle cx="13" cy="40" r=".8"/><circle cx="107" cy="40" r=".8"/></g>`;
}

function shotPitch(points, opposition=false) {
  const circles=points.map(point=>`<circle class="map-shot ${point.outcome==='Goal'?'is-goal':''}" cx="${point.x}" cy="${point.y}" r="${Math.max(1.1,Math.sqrt(Number(point.xg)||.01)*4.5)}"><title>${esc(point.outcome)} · ${fmt(point.xg,2)} xG</title></circle>`).join('');
  return `<div class="analysis-pitch ${opposition?'opposition-pitch':''}"><svg viewBox="0 0 120 80" role="img" aria-label="${opposition?'Shots conceded':'Shot locations'}">${pitchLines()}${circles}</svg><span class="attack-direction">ATTACKING →</span></div>`;
}

function pressurePitch(points) {
  const dots=points.map(point=>`<circle class="map-pressure ${point.counterpress?'is-counterpress':''}" cx="${point.x}" cy="${point.y}" r="1"><title>${point.counterpress?'Counterpress':'Pressure'}</title></circle>`).join('');
  return `<div class="analysis-pitch"><svg viewBox="0 0 120 80" role="img" aria-label="Pressure event locations">${pitchLines()}${dots}</svg><span class="attack-direction">ATTACKING →</span></div>`;
}

function progressionPitch(actions) {
  const paths=actions.map(action=>`<g class="map-action ${action.type==='Carry'?'is-carry':''}"><line x1="${action.x}" y1="${action.y}" x2="${action.end_x}" y2="${action.end_y}"/><circle cx="${action.end_x}" cy="${action.end_y}" r=".65"/><title>${esc(action.type)} · ${action.x},${action.y} to ${action.end_x},${action.end_y}</title></g>`).join('');
  return `<div class="analysis-pitch"><svg viewBox="0 0 120 80" role="img" aria-label="Progressive passes and carries">${pitchLines()}${paths}</svg><span class="attack-direction">ATTACKING →</span></div>`;
}

function positionCoordinate(position,index) {
  const name=position.toLowerCase();
  const side=name.includes('right')?24:name.includes('left')?56:40;
  if(name.includes('goalkeeper'))return [8,40];
  if(name.includes('back'))return [name.includes('wing')?34:27,side];
  if(name.includes('defensive midfield'))return [46,side];
  if(name.includes('center midfield')||name.includes('central midfield'))return [59,side];
  if(name.includes('attacking midfield'))return [75,side];
  if(name.includes('midfield'))return [66,side];
  if(name.includes('wing'))return [84,side];
  if(name.includes('forward'))return [100,side];
  return [18+index*8,40];
}

function positionAbbreviation(position) {
  const known={'Goalkeeper':'GK','Right Back':'RB','Left Back':'LB','Right Center Back':'RCB','Left Center Back':'LCB','Center Back':'CB','Right Wing Back':'RWB','Left Wing Back':'LWB','Right Defensive Midfield':'RDM','Left Defensive Midfield':'LDM','Center Defensive Midfield':'DM','Right Center Midfield':'RCM','Left Center Midfield':'LCM','Center Midfield':'CM','Right Midfield':'RM','Left Midfield':'LM','Right Attacking Midfield':'RAM','Left Attacking Midfield':'LAM','Center Attacking Midfield':'AM','Right Wing':'RW','Left Wing':'LW','Right Center Forward':'RCF','Left Center Forward':'LCF','Center Forward':'CF'};
  return known[position]||position.split(' ').map(word=>word[0]).join('').slice(0,3).toUpperCase();
}

function formationPitch(positions) {
  const nodes=positions.map((position,index)=>{const [x,y]=positionCoordinate(position,index);return `<g class="shape-node" transform="translate(${x} ${y})"><circle r="4.2"/><text text-anchor="middle" dy="1.35">${esc(positionAbbreviation(position))}</text><title>${esc(position)}</title></g>`;}).join('');
  return `<div class="analysis-pitch formation-pitch"><svg viewBox="0 0 120 80" role="img" aria-label="Most-used starting formation">${pitchLines()}${nodes}</svg><span class="attack-direction">ATTACKING →</span></div>`;
}

function trendChart(rows) {
  if(!rows.length)return '';
  const width=760,height=220,pad=28,maxValue=Math.max(...rows.flatMap(row=>[row.xg_for,row.xg_against]),1);
  const point=(row,index,key)=>`${pad+index*(width-pad*2)/Math.max(rows.length-1,1)},${height-pad-(row[key]/maxValue)*(height-pad*2)}`;
  const forPoints=rows.map((row,index)=>point(row,index,'xg_for')).join(' ');
  const againstPoints=rows.map((row,index)=>point(row,index,'xg_against')).join(' ');
  return `<div class="trend-chart"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Match by match expected goals trend"><g class="chart-grid"><line x1="${pad}" y1="${height/2}" x2="${width-pad}" y2="${height/2}"/><line x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}"/></g><polyline class="xg-for-line" points="${forPoints}"/><polyline class="xg-against-line" points="${againstPoints}"/>${rows.map((row,index)=>{const [x,y]=point(row,index,'xg_for').split(',');return `<circle class="chart-point" cx="${x}" cy="${y}" r="3"><title>MW ${row.match_week}: ${fmt(row.xg_for,2)} xG for, ${fmt(row.xg_against,2)} against</title></circle>`;}).join('')}</svg><div class="chart-legend"><span><i class="legend-for"></i>xG for</span><span><i class="legend-against"></i>xG against</span></div></div>`;
}

function ordinal(value) {
  const mod100=value%100;
  if(mod100>=11&&mod100<=13)return `${value}TH`;
  return `${value}${value%10===1?'ST':value%10===2?'ND':value%10===3?'RD':'TH'}`;
}

function renderTeamIntelligence(data) {
  const t=data.team,s=data.style.metrics,a=data.attacking,d=data.defending,b=data.ball_movement,f=data.formations;
  const recent=[...data.form].reverse().slice(0,10);
  const channelTotal=Object.values(b.entry_channels).reduce((sum,value)=>sum+value,0)||1;
  const formationRows=f.distribution.map(row=>`<div class="formation-row"><strong>${esc(row.formation)}</strong><div><span style="width:${row.share_pct}%"></span></div><em>${row.starts} starts · ${fmt(row.share_pct,1)}%</em></div>`).join('');
  const methods=Object.entries(data.methodology).map(([key,value])=>`<li><strong>${esc(key.replaceAll('_',' '))}:</strong> ${esc(value)}</li>`).join('');
  $('#team-intelligence').innerHTML=`
    <button type="button" class="back-to-clubs" id="back-to-clubs">← All 20 clubs</button>
    <article class="club-hero">
      <div class="club-hero-identity">${crest(t.team_name,'club-hero-crest')}<div><p class="section-kicker">${t.position===1?'CHAMPIONS':`FINAL POSITION · ${ordinal(t.position)}`}</p><h2>${esc(t.team_name)}</h2><p>${esc(t.manager)} · ${esc(t.stadium.trim())}</p></div></div>
      <div class="club-hero-record"><span><strong>${t.points}</strong> points</span><span><strong>${t.won}</strong> wins</span><span><strong>${t.goal_difference>0?'+':''}${t.goal_difference}</strong> goal diff.</span><div class="recent-form" aria-label="Last five results">${t.recent_form.split('').map(resultPill).join('')}</div></div>
    </article>
    <nav class="team-section-nav" aria-label="Club analysis sections">${[['team-overview','Overview'],['team-form','Form'],['team-style','Playing style'],['team-ball','Ball movement'],['team-attack','Attack'],['team-defence','Defence'],['team-shape','Shape & maps']].map(([id,label])=>`<button type="button" data-team-anchor="${id}">${label}</button>`).join('')}</nav>
    <section class="team-analysis-section" id="team-overview"><div class="analysis-heading"><div><p class="section-kicker">SEASON OVERVIEW</p><h3>The season in numbers</h3></div><p>Final Premier League record and core output across all 38 matches.</p></div><div class="club-metric-grid">${teamMetric('League position',`#${t.position}`,`${t.points} points`)}${teamMetric('Record',`${t.won}-${t.drawn}-${t.lost}`,'W-D-L')}${teamMetric('Goals',fmt(t.gf),`${fmt(t.xg_for,1)} xG`)}${teamMetric('Goals against',fmt(t.ga),`${fmt(t.xg_against,1)} xGA`)}${teamMetric('Goal difference',`${t.goal_difference>0?'+':''}${t.goal_difference}`,'Actual goals')}${teamMetric('Average possession',`${fmt(t.average_possession_pct,1)}%`,'Per match')}${teamMetric('Shots',fmt(t.shots_for),`${fmt(t.shots_for/t.played,1)} per match`)}${teamMetric('Clean sheets',fmt(t.clean_sheets),`${fmt(100*t.clean_sheets/t.played,0)}% of matches`)}</div><div class="venue-grid"><article><span>HOME RECORD</span><strong>${t.home_record.won}W · ${t.home_record.drawn}D · ${t.home_record.lost}L</strong><small>${t.home_record.points} points · ${t.home_record.gf}–${t.home_record.ga} goals</small></article><article><span>AWAY RECORD</span><strong>${t.away_record.won}W · ${t.away_record.drawn}D · ${t.away_record.lost}L</strong><small>${t.away_record.points} points · ${t.away_record.gf}–${t.away_record.ga} goals</small></article></div></section>
    <section class="team-analysis-section" id="team-form"><div class="analysis-heading"><div><p class="section-kicker">RESULTS & FORM</p><h3>How the season developed</h3></div><p>Match-by-match xG plus the ten most recent league results.</p></div><article class="analysis-card"><div class="analysis-card-heading"><h4>Expected-goals trend</h4><span>All 38 matches</span></div>${trendChart(data.form)}</article><div class="recent-results">${recent.map(row=>`<article><div>${resultPill(row.result)}<span><strong>${esc(row.opponent)}</strong><small>MW ${row.match_week} · ${row.venue}</small></span></div><strong>${row.goals_for}–${row.goals_against}</strong><em>${fmt(row.xg_for,2)}–${fmt(row.xg_against,2)} xG</em></article>`).join('')}</div></section>
    <section class="team-analysis-section" id="team-style"><div class="analysis-heading"><div><p class="section-kicker">TACTICAL IDENTITY</p><h3>What their football looked like</h3></div><p>Descriptive labels supported by direct event statistics—not a composite score.</p></div><div class="style-banner"><div class="style-tags">${data.style.labels.map(label=>`<span>${esc(label)}</span>`).join('')}</div><p>${esc(data.style.summary)}</p></div><div class="club-metric-grid style-metric-grid">${teamMetric('Possession',`${fmt(s.average_possession_pct,1)}%`,'Average per match')}${teamMetric('Pass completion',`${fmt(s.pass_completion_pct,1)}%`,'All pass attempts')}${teamMetric('Average pass length',`${fmt(s.average_pass_length_m,1)}m`,'Distribution distance')}${teamMetric('Forward pass share',`${fmt(s.forward_pass_share_pct,1)}%`,'Passes moving 3m+ forward')}${teamMetric('Passes per possession',fmt(s.passes_per_possession,1),'Sequence length')}${teamMetric('Possession duration',`${fmt(s.average_possession_duration_sec,1)}s`,'Average sequence')}${teamMetric('Pressure height',`${fmt(s.average_pressure_height,1)}/120`,'Average x location')}${teamMetric('PPDA proxy',fmt(s.ppda_proxy,1),'Lower = more aggressive')}</div></section>
    <section class="team-analysis-section" id="team-ball"><div class="analysis-heading"><div><p class="section-kicker">PASSING & PROGRESSION</p><h3>How they moved the ball</h3></div><p>Season-wide completed progressive passes and carries, final-third entries and attacking channels.</p></div><div class="spatial-grid"><article class="analysis-card map-card"><div class="analysis-card-heading"><h4>Progressive actions</h4><span><i class="map-key pass-key"></i>Pass <i class="map-key carry-key"></i>Carry</span></div>${progressionPitch(b.progressive_actions)}</article><article class="analysis-card"><div class="analysis-card-heading"><h4>Entry route</h4><span>Final-third entries</span></div><div class="channel-bars">${Object.entries(b.entry_channels).map(([channel,value])=>`<div><span>${esc(channel)}</span><div><i style="width:${100*value/channelTotal}%"></i></div><strong>${value}</strong></div>`).join('')}</div><div class="compact-stat-list"><div><span>Progressive passes</span><strong>${fmt(b.progressive_passes)}</strong><small>${fmt(s.progressive_passes_per_match,1)} / match</small></div><div><span>Progressive carries</span><strong>${fmt(b.progressive_carries)}</strong><small>${fmt(s.progressive_carries_per_match,1)} / match</small></div><div><span>Final-third entries</span><strong>${fmt(b.final_third_entries)}</strong><small>${fmt(s.final_third_entries_per_match,1)} / match</small></div><div><span>Penalty-area entries</span><strong>${fmt(b.box_entries)}</strong><small>${fmt(s.box_entries_per_match,1)} / match</small></div><div><span>Crosses</span><strong>${fmt(b.crosses)}</strong><small>${fmt(s.crosses_per_match,1)} / match</small></div><div><span>Switches</span><strong>${fmt(b.switches)}</strong><small>${fmt(s.switches_per_match,1)} / match</small></div></div></article></div></section>
    <section class="team-analysis-section" id="team-attack"><div class="analysis-heading"><div><p class="section-kicker">ATTACKING ANALYSIS</p><h3>Where chances came from</h3></div><p>Every league shot plotted by location; larger circles represent higher xG chances.</p></div><div class="spatial-grid"><article class="analysis-card map-card"><div class="analysis-card-heading"><h4>Season shot map</h4><span>${a.shots} shots · ${fmt(a.xg,1)} xG</span></div>${shotPitch(a.shot_map)}</article><div class="club-metric-grid attack-stat-grid">${teamMetric('Goals',fmt(a.goals),`${fmt(a.goal_conversion_pct,1)}% conversion`)}${teamMetric('Shots per match',fmt(a.shots_per_match,1),`${a.shots} total`)}${teamMetric('xG per shot',fmt(a.xg_per_shot,3),'Average chance quality')}${teamMetric('Shots in box',`${fmt(a.box_shot_share_pct,1)}%`,'Share of all shots')}${teamMetric('Set-piece shots',`${fmt(a.set_piece_shot_share_pct,1)}%`,'Share of all shots')}${teamMetric('Goals vs xG',`${a.goals-a.xg>=0?'+':''}${fmt(a.goals-a.xg,1)}`,'Finishing difference')}</div></div></section>
    <section class="team-analysis-section" id="team-defence"><div class="analysis-heading"><div><p class="section-kicker">DEFENSIVE ANALYSIS</p><h3>Pressure and chance prevention</h3></div><p>Where pressure was applied and the quality of shots conceded.</p></div><div class="spatial-grid"><article class="analysis-card map-card"><div class="analysis-card-heading"><h4>Pressure map</h4><span><i class="map-key pressure-key"></i>Pressure <i class="map-key counter-key"></i>Counterpress</span></div>${pressurePitch(d.pressure_map)}</article><article class="analysis-card map-card"><div class="analysis-card-heading"><h4>Opposition shot map</h4><span>${d.shots_against} shots faced</span></div>${shotPitch(d.opposition_shot_map,true)}</article></div><div class="club-metric-grid defence-stat-grid">${teamMetric('Goals conceded',fmt(d.goals_against),`${fmt(d.xg_against,1)} xGA`)}${teamMetric('Shots faced / match',fmt(d.shots_against_per_match,1),`${d.shots_against} total`)}${teamMetric('xG / shot faced',fmt(d.xg_per_shot_against,3),'Chance quality allowed')}${teamMetric('Pressures / match',fmt(d.pressures_per_match,1),'All pressure events')}${teamMetric('High pressure share',`${fmt(s.high_pressure_share_pct,1)}%`,'Pressures at x ≥ 80')}${teamMetric('Counterpress share',`${fmt(d.counterpress_share_pct,1)}%`,'Of pressure events')}${teamMetric('Defensive line height',`${fmt(d.defensive_action_height,1)}/120`,'Average action x')}${teamMetric('PPDA proxy',fmt(d.ppda_proxy,1),'Lower = more aggressive')}</div></section>
    <section class="team-analysis-section" id="team-shape"><div class="analysis-heading"><div><p class="section-kicker">FORMATION & SPATIAL SUMMARY</p><h3>Their most-used team shape</h3></div><p>Starting formations recorded in StatsBomb lineups. This section describes team shape without adding squad-contribution rankings.</p></div><div class="spatial-grid"><article class="analysis-card map-card"><div class="analysis-card-heading"><h4>${esc(f.most_used)} base shape</h4><span>${f.distribution[0]?.starts||0} league starts</span></div>${formationPitch(f.shape_positions)}</article><article class="analysis-card"><div class="analysis-card-heading"><h4>Formation usage</h4><span>Starting shapes</span></div><div class="formation-distribution">${formationRows}</div></article></div><details class="methodology-details"><summary>How these team metrics are calculated</summary><ul>${methods}</ul><p>All analysis covers Premier League 2015/16 StatsBomb Open Data. It is descriptive analysis, not a rating of team quality.</p></details></section>`;
  $('#back-to-clubs').onclick=closeTeam;
  $$('[data-team-anchor]').forEach(button=>button.onclick=()=>document.getElementById(button.dataset.teamAnchor)?.scrollIntoView({behavior:'smooth',block:'start'}));
}

async function openTeam(teamId) {
  if(!teamId)return;
  state.selectedTeamId=Number(teamId);
  $('#team-select').value=String(teamId);
  $('#team-directory').hidden=true;
  const detail=$('#team-intelligence');detail.hidden=false;loading(detail);
  document.getElementById('page-teams')?.scrollIntoView({top:0,behavior:'smooth'});
  try {
    const data=state.teamProfiles[teamId]||await api(`/api/v1/teams/${teamId}/intelligence`);
    if(!data)throw new Error('Club intelligence is not available in this build.');
    state.teamProfiles[teamId]=data;renderTeamIntelligence(data);
  } catch(error){detail.innerHTML='<div class="empty-state"><h3>Unable to load this club analysis</h3></div>';toast(error.message);}
}

function closeTeam() {
  state.selectedTeamId=null;
  $('#team-intelligence').hidden=true;
  $('#team-directory').hidden=false;
  document.getElementById('page-teams')?.scrollIntoView({behavior:'smooth',block:'start'});
}
