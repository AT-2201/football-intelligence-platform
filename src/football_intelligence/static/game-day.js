/* Game Day Planner: historical formation, XI, substitutions and contingencies. */

function initGameDayControls(){
  $('#game-day-team').addEventListener('change',()=>loadGameDayTeam(true));
  $('#game-day-fixture').addEventListener('change',()=>renderSelectedGameDayPlan(false));
  $('#run-game-day').addEventListener('click',()=>renderSelectedGameDayPlan(false));
}

async function loadGameDayPlanner(){
  const output=$('#game-day-workspace');loading(output);
  try{
    state.gameDayTeams=state.teams.length?state.teams:await api('/api/v1/teams');
    state.gameDayTeams.sort((a,b)=>a.team_name.localeCompare(b.team_name));
    $('#game-day-team').innerHTML=state.gameDayTeams.map(team=>`<option value="${team.team_id}">${esc(team.team_name)}</option>`).join('');
    const preferred=state.gameDayTeams.find(team=>team.team_name==='Leicester City')||state.gameDayTeams[0];
    if(preferred)$('#game-day-team').value=String(preferred.team_id);
    await loadGameDayTeam(true);
  }catch(error){output.innerHTML='';toast(error.message);}
}

async function loadGameDayTeam(renderLatest){
  const teamId=Number($('#game-day-team').value),fixture=$('#game-day-fixture');
  fixture.innerHTML='<option>Loading fixtures…</option>';
  try{
    if(!state.gameDayWorkspaces[teamId])state.gameDayWorkspaces[teamId]=await api(`/api/v1/game-day/teams/${teamId}`);
    const workspace=state.gameDayWorkspaces[teamId];
    fixture.innerHTML=[...workspace.plans].reverse().map(plan=>`<option value="${plan.fixture.match_id}">MW ${plan.fixture.match_week} · ${plan.fixture.venue==='Home'?'vs':'at'} ${esc(plan.fixture.opponent_name)} · ${plan.fixture.date}</option>`).join('');
    if(renderLatest&&workspace.plans.length){fixture.value=String(workspace.plans.at(-1).fixture.match_id);renderSelectedGameDayPlan(false);}
  }catch(error){toast(error.message);fixture.innerHTML='<option>Unable to load fixtures</option>';}
}

function gameDayWorkspace(){return state.gameDayWorkspaces[Number($('#game-day-team').value)];}

function selectedGameDayPlan(){
  const workspace=gameDayWorkspace(),matchId=Number($('#game-day-fixture').value);
  return workspace?.plans.find(plan=>plan.fixture.match_id===matchId);
}

function adjustedGameDayLineup(plan){
  const unavailable=state.gameDayUnavailable,lineup=plan.predicted_xi.map(player=>({...player}));
  const used=new Set(lineup.filter(player=>!unavailable.has(player.player_id)).map(player=>player.player_id));
  for(let index=0;index<lineup.length;index++){
    const current=lineup[index];
    if(!unavailable.has(current.player_id))continue;
    const replacement=plan.candidate_pool.find(candidate=>!unavailable.has(candidate.player_id)&&!used.has(candidate.player_id)&&candidate.position_group===current.position_group)
      ||plan.candidate_pool.find(candidate=>!unavailable.has(candidate.player_id)&&!used.has(candidate.player_id)&&candidate.position_group!=='Goalkeeper');
    if(replacement){lineup[index]={...replacement,predicted_position:current.predicted_position,availability_adjustment:true,replaced_player_name:current.player_name};used.add(replacement.player_id);}
  }
  return lineup;
}

function gameDayPitch(players){
  const nodes=players.map((player,index)=>{const[x,y]=positionCoordinate(player.predicted_position,index),surname=player.player_name.split(' ').at(-1).slice(0,12);return `<g class="gd-player ${player.availability_adjustment?'adjusted':''}" transform="translate(${x} ${y})"><circle r="5"/><text class="gd-role" text-anchor="middle" dy="1.3">${index+1}</text><text class="gd-name" text-anchor="middle" y="8">${esc(surname)}</text><title>${esc(player.player_name)} · ${esc(player.predicted_position)} · ${player.start_probability}%</title></g>`;}).join('');
  return `<div class="gd-pitch"><svg viewBox="0 0 120 80" role="img" aria-label="Predicted starting eleven">${pitchLines()}${nodes}</svg><span>ATTACKING →</span></div>`;
}

function formationProbabilityBars(forecast){return forecast.probabilities.map(row=>`<div class="formation-probability"><strong>${esc(row.formation)}</strong><div><i style="width:${row.probability}%"></i></div><span>${fmt(row.probability,1)}%</span></div>`).join('');}

function backtestCards(backtest){return `<div class="gd-backtest"><article><span>Formation accuracy</span><strong>${fmt(backtest.formation_accuracy_pct,1)}%</strong><small>Walk-forward fixtures</small></article><article><span>Correct starters</span><strong>${fmt(backtest.average_correct_starters,2)}/11</strong><small>Average predicted XI</small></article><article><span>Subbed-off hit rate</span><strong>${fmt(backtest.substitute_off_top3_accuracy_pct,1)}%</strong><small>Top-three forecast</small></article><article><span>Subbed-on hit rate</span><strong>${fmt(backtest.substitute_on_top3_accuracy_pct,1)}%</strong><small>Top-three forecast</small></article></div>`;}

function availabilityEditor(plan){
  return `<details class="gd-availability"><summary><span><strong>Availability editor</strong><small>Exclude injured, suspended, rested or otherwise unavailable players</small></span><em>${state.gameDayUnavailable.size} unavailable</em></summary><div class="availability-grid">${plan.candidate_pool.map(player=>`<label class="${state.gameDayUnavailable.has(player.player_id)?'unavailable':''}"><input type="checkbox" data-game-day-unavailable="${player.player_id}" ${state.gameDayUnavailable.has(player.player_id)?'checked':''}><span><strong>${esc(player.player_name)}</strong><small>${esc(player.primary_position)} · ${fmt(player.start_probability)}% start probability</small></span></label>`).join('')}</div><p>${esc(plan.availability.note)}</p></details>`;
}

function lineupEvidence(players){return `<div class="gd-lineup-list">${players.map(player=>`<article><span class="gd-shirt">${positionAbbreviation(player.predicted_position)}</span><div><strong>${esc(player.player_name)}</strong><small>${esc(player.predicted_position)}${player.availability_adjustment?` · replaces ${esc(player.replaced_player_name)}`:''}</small></div><em>${fmt(player.start_probability)}%</em><p>${esc(player.reasons?.[0]||'Selected by the constrained lineup forecast.')}</p></article>`).join('')}</div>`;}

function opponentPanel(plan){const o=plan.opponent,m=o.metrics;return `<div class="gd-opponent-grid"><article class="gd-card"><div class="gd-card-heading"><div><p class="section-kicker">OPPOSITION BRIEF</p><h3>${crest(o.team_name,'list-crest')}${esc(o.team_name)}</h3></div><span>Last ${o.matches_used} matches · ${esc(o.recent_form)}</span></div><div class="gd-opponent-metrics"><span><small>Possession</small><strong>${fmt(m.possession_pct,1)}%</strong></span><span><small>Pass completion</small><strong>${fmt(m.pass_completion_pct,1)}%</strong></span><span><small>Shots</small><strong>${fmt(m.shots_per_match,1)}</strong></span><span><small>xG / match</small><strong>${fmt(m.xg_per_match,2)}</strong></span><span><small>xGA / match</small><strong>${fmt(m.xg_against_per_match,2)}</strong></span></div><div class="gd-strengths"><div><strong>Strengths to prepare for</strong><ul>${o.strengths.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div><div><strong>Possible openings</strong><ul>${o.weaknesses.map(item=>`<li>${esc(item)}</li>`).join('')}</ul></div></div></article><article class="gd-card match-importance"><p class="section-kicker">MATCH CONTEXT</p><div class="importance-score"><strong>${plan.importance.score}</strong><span>${esc(plan.importance.label)} importance</span></div><p>#${plan.importance.team_position} ${esc(plan.fixture.team_name)} · ${plan.importance.team_points} pts<br>#${plan.importance.opponent_position} ${esc(plan.fixture.opponent_name)} · ${plan.importance.opponent_points} pts</p><ul>${plan.importance.reasons.map(item=>`<li>${esc(item)}</li>`).join('')}</ul><small>${esc(plan.importance.method)}</small></article></div><article class="gd-card matchup-plan"><div><p class="section-kicker">ANALYST MATCHUP NOTES</p><h3>How the forecast connects to the opponent</h3></div><ol>${plan.matchup_notes.map((item,index)=>`<li><span>0${index+1}</span>${esc(item)}</li>`).join('')}</ol></article>`;}

function substitutionCards(plan,scenario){
  const rows=plan.substitution_forecast[scenario].filter(row=>!state.gameDayUnavailable.has(row.off_player_id)&&!state.gameDayUnavailable.has(row.on_player_id));
  if(!rows.length)return '<div class="gd-empty-inline">No earlier manager-specific replacement pair remains after the selected availability changes.</div>';
  return `<div class="gd-sub-list">${rows.slice(0,4).map((row,index)=>`<article><span>0${index+1}</span><div><strong>${esc(row.off_player_name)} <i>→</i> ${esc(row.on_player_name)}</strong><p>${esc(row.reason)}</p></div><em>${fmt(row.probability,1)}%<small>${row.minute_from}–${row.minute_to} min</small></em></article>`).join('')}</div>`;
}

function renderSubstitutionScenario(plan,scenario){
  state.gameDaySubScenario=scenario;
  $$('[data-sub-scenario]').forEach(button=>button.classList.toggle('active',button.dataset.subScenario===scenario));
  $('#gd-substitution-output').innerHTML=substitutionCards(plan,scenario);
}

function redCardPlan(plan,lineup){
  const playerId=Number($('#gd-red-player').value),minute=Number($('#gd-red-minute').value||65),score=$('#gd-red-score').value;
  const sent=lineup.find(player=>player.player_id===playerId)||lineup[0],group=sent.position_group;
  const availableBench=plan.candidate_pool.filter(player=>!lineup.some(starter=>starter.player_id===player.player_id)&&!state.gameDayUnavailable.has(player.player_id));
  let shape='4-4-1',change='No immediate substitution required',withdrawn=null,replacement=null;
  const lowestForward=[...lineup].filter(player=>['Forward','Wide Player'].includes(player.position_group)&&player.player_id!==sent.player_id).sort((a,b)=>a.start_probability-b.start_probability)[0];
  if(group==='Goalkeeper'){
    withdrawn=lowestForward;replacement=availableBench.find(player=>player.position_group==='Goalkeeper');change=withdrawn&&replacement?`${withdrawn.player_name} off · ${replacement.player_name} on`:'Introduce the reserve goalkeeper for an attacking player';
  }else if(['Centre Back','Full Back'].includes(group)){
    withdrawn=lowestForward;replacement=availableBench.find(player=>['Centre Back','Full Back'].includes(player.position_group));change=withdrawn&&replacement?`${withdrawn.player_name} off · ${replacement.player_name} on`:'Replace an attacker with the best available defender';
  }else if(['Central Midfielder','Defensive Midfielder','Wide Player'].includes(group)){
    shape=score==='leading'?'4-4-1':'4-3-2';change='Narrow the midfield and preserve one counterattacking outlet';
  }
  const block=score==='leading'?'Protect the central lane in a compact deeper block and counter into space.':score==='trailing'?'Keep one high outlet, press selectively and avoid leaving the back line exposed.':'Use a compact mid-block first, then reassess after the next ten-minute phase.';
  const urgency=minute<35?'Preserve substitutions where possible; the team must manage a long ten-player phase.':minute<70?'Make the structural decision within the next stoppage.':'Prioritise game-state protection and simple role instructions.';
  $('#gd-red-output').innerHTML=`<div class="contingency-result"><div><span>RECOMMENDED TEN-PLAYER SHAPE</span><strong>${shape}</strong></div><div><span>PERSONNEL RESPONSE</span><strong>${esc(change)}</strong></div><ol><li>${esc(block)}</li><li>${esc(urgency)}</li><li>Protect the zone vacated by ${esc(sent.player_name)} (${esc(sent.predicted_position)}).</li></ol><small>Conditional tactical guidance informed by the forecast squad and ${plan.red_card_contingency.historical_team_send_offs_before_match} earlier team send-off(s). It does not predict a red card.</small></div>`;
}

function contingencyBuilder(plan,lineup){return `<article class="gd-card gd-contingency"><div class="gd-card-heading"><div><p class="section-kicker">RED-CARD CONTINGENCY</p><h3>Prepare the ten-player response</h3></div><span>Conditional plan · not a red-card prediction</span></div><div class="contingency-controls"><label>Player sent off<select id="gd-red-player">${lineup.map(player=>`<option value="${player.player_id}">${esc(player.player_name)} · ${esc(player.predicted_position)}</option>`).join('')}</select></label><label>Minute<input id="gd-red-minute" type="number" min="1" max="90" value="65"></label><label>Score state<select id="gd-red-score"><option value="leading">Leading</option><option value="level" selected>Level</option><option value="trailing">Trailing</option></select></label></div><div id="gd-red-output"></div></article>`;}

function renderSelectedGameDayPlan(preserveAvailability){
  const workspace=gameDayWorkspace(),plan=selectedGameDayPlan();if(!workspace||!plan)return;
  state.selectedGameDayPlan=plan;
  if(!preserveAvailability)state.gameDayUnavailable=new Set(plan.availability.inferred_unavailable_player_ids);
  const lineup=adjustedGameDayLineup(plan),fixture=plan.fixture,scenario=state.gameDaySubScenario||'level';
  $('#game-day-workspace').innerHTML=`<article class="gd-hero"><div><p class="section-kicker">MATCHWEEK ${fixture.match_week} · ${fixture.venue.toUpperCase()} · FORECAST CUTOFF ${plan.training_window.cutoff_date}</p><h2>${crest(fixture.team_name,'club-hero-crest')}${esc(fixture.team_name)} <span>${fixture.venue==='Home'?'vs':'at'}</span> ${crest(fixture.opponent_name,'club-hero-crest')}${esc(fixture.opponent_name)}</h2><p>Recent form ${esc(plan.recent_form)} · ${plan.training_window.prior_matches} earlier matches available to the model</p></div><span class="leakage-badge">✓ Historical data only</span></article><section class="gd-validation"><div><p class="section-kicker">MODEL VALIDATION</p><h3>Measured before recommendations</h3><p>${esc(workspace.backtest.method)}</p></div>${backtestCards(workspace.backtest)}</section><div class="gd-primary-grid"><article class="gd-card"><div class="gd-card-heading"><div><p class="section-kicker">FORMATION FORECAST</p><h3>${esc(plan.formation_forecast.predicted)} most likely shape</h3></div><span>Recent formation use + venue</span></div>${formationProbabilityBars(plan.formation_forecast)}${gameDayPitch(lineup)}</article><article class="gd-card"><div class="gd-card-heading"><div><p class="section-kicker">PREDICTED XI</p><h3>Selection evidence</h3></div><span>Probabilities are not ratings</span></div>${lineupEvidence(lineup)}</article></div>${availabilityEditor(plan)}${opponentPanel(plan)}<article class="gd-card gd-substitutions"><div class="gd-card-heading"><div><p class="section-kicker">SUBSTITUTION FORECAST</p><h3>Likely in-game changes</h3></div><span>Manager-specific prior patterns</span></div><div class="scenario-tabs"><button data-sub-scenario="leading">If leading</button><button data-sub-scenario="level">If level</button><button data-sub-scenario="trailing">If trailing</button></div><div id="gd-substitution-output"></div></article>${contingencyBuilder(plan,lineup)}<details class="methodology-details gd-method"><summary>How this model works and what it cannot know</summary><dl><div><dt>Formation</dt><dd>${esc(workspace.model.formation)}</dd></div><div><dt>Starting XI</dt><dd>${esc(workspace.model.lineup)}</dd></div><div><dt>Substitutions</dt><dd>${esc(workspace.model.substitutions)}</dd></div><div><dt>Scope</dt><dd>${esc(workspace.model.scope)}</dd></div></dl><p>Selected-match validation: ${plan.validation.correct_starters}/11 starters correct · predicted ${esc(plan.formation_forecast.predicted)}, actual ${esc(plan.formation_forecast.actual_for_validation)}.</p></details>`;
  $$('[data-game-day-unavailable]').forEach(input=>input.onchange=event=>{const id=Number(event.target.dataset.gameDayUnavailable);event.target.checked?state.gameDayUnavailable.add(id):state.gameDayUnavailable.delete(id);const scroll=window.scrollY;renderSelectedGameDayPlan(true);window.scrollTo(0,scroll);});
  $$('[data-sub-scenario]').forEach(button=>button.onclick=()=>renderSubstitutionScenario(plan,button.dataset.subScenario));
  renderSubstitutionScenario(plan,scenario);
  ['#gd-red-player','#gd-red-minute','#gd-red-score'].forEach(selector=>$(selector).addEventListener('change',()=>redCardPlan(plan,adjustedGameDayLineup(plan))));
  redCardPlan(plan,lineup);
}
