(function () {
  const metrics = ['goals', 'xg', 'shots', 'passes', 'carries', 'pressures', 'tackles', 'interceptions'];
  const positionGroups = ['Goalkeeper', 'Centre Back', 'Full Back', 'Defensive Midfielder', 'Central Midfielder', 'Wide Attacker', 'Forward'];
  const needProfiles = {
    balanced_profile: {label:'Balanced playing profile', metrics},
    goal_threat: {label:'More goal threat', metrics:['goals','xg','shots']},
    passing_involvement: {label:'More passing involvement', metrics:['passes']},
    ball_carrying: {label:'More ball carrying', metrics:['carries']},
    pressing: {label:'More pressing intensity', metrics:['pressures','tackles']},
    defensive_activity: {label:'More defensive activity', metrics:['tackles','interceptions','pressures']}
  };
  const clone = value => JSON.parse(JSON.stringify(value));

  function similarityDeviations(data) {
    const benchmark = data.scoutingBase.filter(player => player.minutes >= 450);
    const pool = benchmark.length ? benchmark : data.scoutingBase;
    return Object.fromEntries(metrics.map(metric => {
      const mean = pool.reduce((sum,player) => sum + player.per_90[metric], 0) / pool.length;
      const variance = pool.reduce((sum,player) => sum + Math.pow(player.per_90[metric] - mean, 2), 0) / pool.length;
      return [metric, Math.sqrt(variance) || 1];
    }));
  }

  function similarityScore(first, second, deviations) {
    const distance = Math.sqrt(metrics.reduce((sum,metric) => {
      const difference = (first.per_90[metric] - second.per_90[metric]) / deviations[metric];
      return sum + difference * difference;
    }, 0) / metrics.length);
    return Number((100 / (1 + distance)).toFixed(1));
  }

  function positionGroup(position) {
    const normalized = position.toLowerCase();
    if (normalized.includes('goalkeeper')) return 'Goalkeeper';
    if (normalized.includes('back') && normalized.includes('center')) return 'Centre Back';
    if (normalized.includes('back')) return 'Full Back';
    if (normalized.includes('wing') || normalized.includes('left midfield') || normalized.includes('right midfield')) return 'Wide Attacker';
    if (normalized.includes('defensive midfield')) return 'Defensive Midfielder';
    if (normalized.includes('midfield')) return 'Central Midfielder';
    if (normalized.includes('forward')) return 'Forward';
    return 'Other';
  }

  function filteredPool(data, params) {
    const minMinutes = Number(params.get('min_minutes') || 0);
    const position = (params.get('position') || '').toLowerCase();
    const search = (params.get('search') || '').toLowerCase();
    const limit = Number(params.get('limit') || 50);
    const pool = data.scoutingBase.filter(player =>
      player.minutes >= minMinutes &&
      (!position || player.position.toLowerCase().includes(position)) &&
      (!search || `${player.player_name} ${player.team_name}`.toLowerCase().includes(search))
    ).map(clone);
    for (const player of pool) {
      for (const metric of metrics) {
        player.totals[metric] ??= metric === 'xg'
          ? Number((player.per_90[metric] * player.minutes / 90).toFixed(2))
          : Math.round(player.per_90[metric] * player.minutes / 90);
      }
    }
    return pool.sort((a,b) => b.minutes - a.minutes).slice(0, limit);
  }

  function similarPlayers(data, playerId, params) {
    const minMinutes = Number(params.get('min_minutes') || 450);
    const limit = Number(params.get('limit') || 10);
    const sourceTarget = data.scoutingBase.find(player => player.player_id === playerId);
    if (!sourceTarget) return undefined;
    const target = clone(sourceTarget);
    const group = positionGroup(target.position);
    const candidates = data.scoutingBase.filter(player => player.player_id !== playerId && player.minutes >= minMinutes && positionGroup(player.position) === group).map(clone);
    const deviations = similarityDeviations(data);
    for (const player of candidates) {
      const comparisons = metrics.map(metric => ({metric, target:Number(target.per_90[metric].toFixed(2)), candidate:Number(player.per_90[metric].toFixed(2)), difference:Number((player.per_90[metric]-target.per_90[metric]).toFixed(2)), standardizedGap:Math.abs(player.per_90[metric]-target.per_90[metric])/deviations[metric]}));
      player.match_reasons = [...comparisons].sort((a,b) => a.standardizedGap-b.standardizedGap).slice(0,3).map(({standardizedGap,...item}) => item);
      player.trade_offs = [...comparisons].sort((a,b) => b.standardizedGap-a.standardizedGap).slice(0,2).map(({standardizedGap,...item}) => item);
      player.similarity = similarityScore(target, player, deviations);
      player.position_group = group;
    }
    candidates.sort((a,b) => b.similarity - a.similarity);
    target.position_group = group;
    return { target, position_group:group, similar_players:candidates.slice(0, limit), methodology:"Standardized per-90 distance using the shared league-wide 450-minute benchmark; candidates are restricted to the player's position family." };
  }

  function replacementPlayers(data, playerId, params) {
    const source = similarPlayers(data, playerId, new URLSearchParams({
      min_minutes: params.get('min_minutes') || '450',
      limit: String(data.scoutingBase.length)
    }));
    if (!source) return undefined;
    const minSimilarity = Number(params.get('min_similarity') || 0);
    const excludeSameTeam = params.get('exclude_same_team') === 'true';
    const limit = Number(params.get('limit') || 10);
    const candidates = source.similar_players.filter(player =>
      player.similarity >= minSimilarity &&
      (!excludeSameTeam || player.team_id !== source.target.team_id)
    );
    for (const player of candidates) {
      player.minutes_difference = Number((player.minutes - source.target.minutes).toFixed(1));
    }
    return {
      target: source.target,
      position_group: source.position_group,
      replacement_candidates: candidates.slice(0, limit),
      screening: {
        minimum_minutes: Number(params.get('min_minutes') || 450),
        minimum_similarity: minSimilarity,
        same_team_excluded: excludeSameTeam,
        eligible_candidates: candidates.length
      },
      methodology: source.methodology
    };
  }

  function comparePlayers(data, playerIds) {
    const uniqueIds = [...new Set(playerIds)];
    const pool = data.scoutingBase.map(clone);
    const benchmark = pool.filter(player => player.minutes >= 450);
    const deviations = similarityDeviations(data);
    const players = uniqueIds.map(id => pool.find(player => player.player_id === id)).filter(Boolean);
    const metricLeaders = Object.fromEntries(metrics.map(metric => {
      const value = Math.max(...players.map(player => player.per_90[metric]));
      return [metric, {value, player_ids:players.filter(player => player.per_90[metric] === value).map(player => player.player_id)}];
    }));
    const similarities = [];
    for (let i=0; i<players.length; i++) {
      for (let j=i+1; j<players.length; j++) {
        similarities.push({player_a_id:players[i].player_id, player_b_id:players[j].player_id, similarity:similarityScore(players[i], players[j], deviations)});
      }
    }
    similarities.sort((a,b) => b.similarity - a.similarity);
    return {players, metric_leaders:metricLeaders, similarities, benchmark:{minimum_minutes:450, players:benchmark.length, method:'Direct season totals and per-90 rates', visual_scale:'Bars are scaled only against the selected players.'}};
  }

  function weightedProfile(records) {
    const totalMinutes = records.reduce((sum,player) => sum + player.minutes, 0) || 1;
    return Object.fromEntries(metrics.map(metric => [metric, records.reduce((sum,player) => sum + player.per_90[metric] * player.minutes, 0) / totalMinutes]));
  }

  function needLevel(corePlayers, topShare) {
    if (corePlayers <= 1 || topShare >= 0.68) return ['High', 3];
    if (corePlayers <= 2 || topShare >= 0.52) return ['Medium', 2];
    return ['Covered', 1];
  }

  function squadNeeds(data, teamId) {
    const teamPlayers = data.scoutingBase.filter(player => player.team_id === teamId);
    if (!teamPlayers.length) return undefined;
    const diagnostics = positionGroups.map(group => {
      const players = teamPlayers.filter(player => positionGroup(player.position) === group).sort((a,b) => b.minutes-a.minutes);
      const totalMinutes = players.reduce((sum,player) => sum + player.minutes, 0);
      const corePlayers = players.filter(player => player.minutes >= 450).length;
      const topShare = totalMinutes ? players[0].minutes / totalMinutes : 1;
      const [level,priority] = needLevel(corePlayers,topShare);
      let reason;
      if (!players.length) reason = 'No player has this as a primary recorded position.';
      else if (corePlayers <= 1) reason = 'Only one player reached the 450-minute evidence threshold.';
      else if (topShare >= 0.68) reason = `${players[0].player_name} supplied ${Math.round(topShare*100)}% of recorded minutes.`;
      else if (corePlayers <= 2) reason = 'Only two players reached the 450-minute evidence threshold.';
      else reason = `${corePlayers} players supplied meaningful league minutes.`;
      return {position_group:group, need_level:level, priority, players:players.length, core_players:corePlayers, total_minutes:Number(totalMinutes.toFixed(1)), top_player_share:Number((topShare*100).toFixed(1)), top_player:players[0]?.player_name || null, reason};
    }).sort((a,b) => b.priority-a.priority || b.top_player_share-a.top_player_share);
    return {team_id:teamId, team_name:teamPlayers[0].team_name, players:teamPlayers.length, diagnostics, methodology:'Coverage risk uses primary position, recorded league minutes, a 450-minute evidence threshold and the share carried by the most-used player.'};
  }

  function band(value, strong=68, good=52) {
    if (value >= strong) return 'Strong';
    if (value >= good) return 'Good';
    return 'Developing';
  }

  function recommendPlayers(data, params) {
    const teamId = Number(params.get('team_id'));
    const scenario = params.get('scenario') || 'replace_player';
    const playerId = Number(params.get('player_id')) || null;
    const requestedPosition = params.get('position');
    const needKey = params.get('need') || 'balanced_profile';
    const minMinutes = Number(params.get('min_minutes') || 450);
    const limit = Number(params.get('limit') || 8);
    const squad = squadNeeds(data,teamId);
    if (!squad) return undefined;
    const teamPlayers = data.scoutingBase.filter(player => player.team_id === teamId);
    const target = scenario === 'replace_player' ? teamPlayers.find(player => player.player_id === playerId) : null;
    const selectedGroup = target ? positionGroup(target.position) : requestedPosition || squad.diagnostics[0].position_group;
    const need = needProfiles[needKey] || needProfiles.goal_threat;
    const teamGroup = teamPlayers.filter(player => positionGroup(player.position) === selectedGroup);
    const leagueGroup = data.scoutingBase.filter(player => positionGroup(player.position) === selectedGroup && player.minutes >= 450);
    const referenceRecords = target ? [target] : teamGroup.length ? teamGroup : leagueGroup;
    const reference = weightedProfile(referenceRecords);
    const deviations = similarityDeviations(data);
    const ranked = data.scoutingBase.filter(player => player.team_id !== teamId && player.minutes >= minMinutes && positionGroup(player.position) === selectedGroup).map(clone).map(candidate => {
      const distance = Math.sqrt(metrics.reduce((sum,metric) => sum + Math.pow((candidate.per_90[metric]-reference[metric])/deviations[metric],2),0)/metrics.length);
      const profileMatch = 100/(1+distance);
      const needZ = need.metrics.reduce((sum,metric) => sum + (candidate.per_90[metric]-reference[metric])/deviations[metric],0)/need.metrics.length;
      const needStrength = Math.max(0,Math.min(100,50+needZ*18));
      const evidence = Math.max(0,Math.min(100,candidate.minutes/2700*100));
      const rankingScore = scenario === 'replace_player' ? profileMatch*.68+needStrength*.17+evidence*.15 : scenario === 'improve_need' ? profileMatch*.30+needStrength*.55+evidence*.15 : profileMatch*.50+needStrength*.25+evidence*.25;
      const evidenceRows = need.metrics.map(metric => ({metric,candidate:Number(candidate.per_90[metric].toFixed(2)),squad_reference:Number(reference[metric].toFixed(2)),difference:Number((candidate.per_90[metric]-reference[metric]).toFixed(2))})).sort((a,b) => b.difference-a.difference);
      const positiveEvidence = evidenceRows.filter(item => item.difference >= 0);
      const why = (positiveEvidence.length ? positiveEvidence : evidenceRows.slice(0,1)).slice(0,3);
      const tradeOffs = metrics.filter(metric => candidate.per_90[metric] < reference[metric]).map(metric => ({metric,candidate:Number(candidate.per_90[metric].toFixed(2)),squad_reference:Number(reference[metric].toFixed(2)),difference:Number((candidate.per_90[metric]-reference[metric]).toFixed(2))})).sort((a,b) => Number(!need.metrics.includes(a.metric))-Number(!need.metrics.includes(b.metric)) || a.difference/deviations[a.metric]-b.difference/deviations[b.metric]).slice(0,2);
      return {...candidate,position_group:selectedGroup,profile_match:Number(profileMatch.toFixed(1)),need_fit:band(needStrength),evidence_confidence:band(evidence,80,45),why_recommended:why,trade_offs:tradeOffs,_ranking_score:rankingScore};
    }).sort((a,b) => b._ranking_score-a._ranking_score);
    ranked.forEach(candidate => delete candidate._ranking_score);
    return {team:{team_id:teamId,team_name:squad.team_name},scenario,position_group:selectedGroup,need:{key:needKey,...need},reference_player:target?safeClone(target):null,squad_reference:Object.fromEntries(metrics.map(metric => [metric,Number(reference[metric].toFixed(2))])),recommendations:ranked.slice(0,limit),screening:{minimum_minutes:minMinutes,eligible_candidates:ranked.length,current_club_excluded:true},methodology:'Recommendations combine similarity to the selected player, the chosen replacement priority and minutes-based evidence. Rankings are screening guidance, not transfer value.'};
  }

  function safeClone(value) { return value ? clone(value) : value; }

  window.portfolioApi = async function (path) {
    const data = window.PORTFOLIO_DATA;
    if (!data) return undefined;
    const url = new URL(path, 'https://portfolio.local');
    const pathname = url.pathname;
    if (pathname === '/api/v1/overview') return clone(data.overview);
    if (pathname === '/api/v1/standings') return clone(data.standings);
    if (pathname === '/api/v1/matches') return clone(data.matches).slice(Number(url.searchParams.get('offset') || 0), Number(url.searchParams.get('limit') || 50));
    if (pathname === '/api/v1/teams') return clone(data.teams);
    if (pathname === '/api/v1/players') {
      const minimum = Number(url.searchParams.get('min_minutes') || 0);
      const team = url.searchParams.get('team_id');
      const limit = Number(url.searchParams.get('limit') || 100);
      return clone(data.players).filter(p => p.minutes >= minimum && (!team || p.team_id === Number(team))).slice(0, limit);
    }
    if (pathname === '/api/v1/scouting/players') return filteredPool(data, url.searchParams);
    if (pathname === '/api/v1/scouting/compare') return comparePlayers(data, url.searchParams.getAll('player_ids').map(Number));
    if (pathname === '/api/v1/scouting/recommendations') return recommendPlayers(data, url.searchParams);
    let needs = pathname.match(/^\/api\/v1\/scouting\/teams\/(\d+)\/needs$/);
    if (needs) return safeClone(squadNeeds(data, Number(needs[1])));
    let match = pathname.match(/^\/api\/v1\/matches\/(\d+)\/events$/);
    if (match) return clone(data.matchShots[match[1]] || []);
    match = pathname.match(/^\/api\/v1\/matches\/(\d+)\/players$/);
    if (match) return clone(data.matchPlayers[match[1]] || []);
    match = pathname.match(/^\/api\/v1\/matches\/(\d+)$/);
    if (match) return clone(data.matchDetails[match[1]]);
    let player = pathname.match(/^\/api\/v1\/scouting\/players\/(\d+)\/similar$/);
    if (player) return similarPlayers(data, Number(player[1]), url.searchParams);
    player = pathname.match(/^\/api\/v1\/scouting\/players\/(\d+)\/replacements$/);
    if (player) return replacementPlayers(data, Number(player[1]), url.searchParams);
    player = pathname.match(/^\/api\/v1\/players\/(\d+)\/matches$/);
    if (player) return clone(data.playerLogs[player[1]] || []).slice(0, Number(url.searchParams.get('limit') || 38));
    player = pathname.match(/^\/api\/v1\/players\/(\d+)$/);
    if (player) return clone(data.playerDetails[player[1]]);
    return undefined;
  };
})();
