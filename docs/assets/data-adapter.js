(function () {
  const metrics = ['goals', 'xg', 'shots', 'passes', 'carries', 'pressures', 'tackles', 'interceptions'];
  const roleProfiles = {
    balanced: {label:'Balanced profile', description:'Weights attacking, possession and defensive output evenly.', weights:{goals:1,xg:1,shots:1,passes:1,carries:1,pressures:1,tackles:1,interceptions:1}},
    progressor: {label:'Ball progressor', description:'Prioritizes passing volume and carrying contribution.', weights:{goals:.35,xg:.45,shots:.35,passes:2.5,carries:2.5,pressures:.6,tackles:.4,interceptions:.4}},
    creator: {label:'Possession creator', description:'Emphasizes passing, carrying and attacking involvement.', weights:{goals:.8,xg:1,shots:.7,passes:2.3,carries:2,pressures:.7,tackles:.35,interceptions:.35}},
    ball_winner: {label:'Ball winner', description:'Prioritizes pressure, tackling and interception activity.', weights:{goals:.25,xg:.25,shots:.25,passes:.8,carries:.45,pressures:2.2,tackles:2.5,interceptions:2.5}},
    goal_threat: {label:'Goal threat', description:'Emphasizes shooting volume, expected goals and goals.', weights:{goals:2.5,xg:2.5,shots:2.2,passes:.35,carries:1,pressures:.55,tackles:.2,interceptions:.2}}
  };
  const clone = value => JSON.parse(JSON.stringify(value));

  function positionGroup(position) {
    const normalized = position.toLowerCase();
    if (normalized.includes('goalkeeper')) return 'Goalkeeper';
    if (normalized.includes('back') && normalized.includes('center')) return 'Centre Back';
    if (normalized.includes('back')) return 'Full Back';
    if (normalized.includes('defensive midfield')) return 'Defensive Midfielder';
    if (normalized.includes('midfield')) return 'Central Midfielder';
    if (normalized.includes('wing')) return 'Wide Attacker';
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
    const roleKey = params.get('role') || 'balanced';
    const role = roleProfiles[roleKey] || roleProfiles.balanced;
    const sourceTarget = data.scoutingBase.find(player => player.player_id === playerId);
    if (!sourceTarget) return undefined;
    const target = clone(sourceTarget);
    const group = positionGroup(target.position);
    const candidates = data.scoutingBase.filter(player => player.player_id !== playerId && player.minutes >= minMinutes && positionGroup(player.position) === group).map(clone);
    const comparison = [...candidates, target];
    const means = Object.fromEntries(metrics.map(metric => [metric, comparison.reduce((sum,p) => sum + p.per_90[metric], 0) / comparison.length]));
    const deviations = Object.fromEntries(metrics.map(metric => {
      const variance = comparison.reduce((sum,p) => sum + Math.pow(p.per_90[metric] - means[metric], 2), 0) / comparison.length;
      return [metric, Math.sqrt(variance) || 1];
    }));
    const weightTotal = metrics.reduce((sum,metric) => sum + role.weights[metric], 0);
    for (const player of candidates) {
      const distance = Math.sqrt(metrics.reduce((sum,metric) => {
        const difference = (player.per_90[metric] - target.per_90[metric]) / deviations[metric];
        return sum + role.weights[metric] * difference * difference;
      }, 0) / weightTotal);
      const comparisons = metrics.map(metric => ({metric, target:Number(target.per_90[metric].toFixed(2)), candidate:Number(player.per_90[metric].toFixed(2)), difference:Number((player.per_90[metric]-target.per_90[metric]).toFixed(2)), weightedGap:Math.abs(player.per_90[metric]-target.per_90[metric])/deviations[metric]*Math.sqrt(role.weights[metric])}));
      player.match_reasons = comparisons.filter(item => role.weights[item.metric] >= .6).sort((a,b) => a.weightedGap-b.weightedGap).slice(0,3).map(({weightedGap,...item}) => item);
      player.trade_offs = comparisons.sort((a,b) => b.weightedGap-a.weightedGap).slice(0,2).map(({weightedGap,...item}) => item);
      player.similarity = Number((100 / (1 + distance)).toFixed(1));
      player.position_group = group;
    }
    candidates.sort((a,b) => b.similarity - a.similarity);
    target.position_group = group;
    const priorityMetrics = [...metrics].sort((a,b) => role.weights[b]-role.weights[a]).slice(0,3);
    return { target, role:{key:roleKey,label:role.label,description:role.description,priority_metrics:priorityMetrics}, position_group:group, similar_players:candidates.slice(0, limit), methodology:"Weighted per-90 distance within the player's position family." };
  }

  function comparePlayers(data, playerIds) {
    const uniqueIds = [...new Set(playerIds)];
    const pool = data.scoutingBase.map(clone);
    const benchmark = pool.filter(player => player.minutes >= 450);
    const distributions = Object.fromEntries(metrics.map(metric => [metric, benchmark.map(player => player.per_90[metric]).sort((a,b) => a-b)]));
    const means = Object.fromEntries(metrics.map(metric => [metric, benchmark.reduce((sum,player) => sum + player.per_90[metric], 0) / benchmark.length]));
    const deviations = Object.fromEntries(metrics.map(metric => {
      const variance = benchmark.reduce((sum,player) => sum + Math.pow(player.per_90[metric] - means[metric], 2), 0) / benchmark.length;
      return [metric, Math.sqrt(variance) || 1];
    }));
    const players = uniqueIds.map(id => pool.find(player => player.player_id === id)).filter(Boolean).map(player => {
      player.relative_profile = Object.fromEntries(metrics.map(metric => [metric, Math.round(100 * distributions[metric].filter(value => value <= player.per_90[metric]).length / distributions[metric].length)]));
      const ranked = [...metrics].sort((a,b) => player.relative_profile[b] - player.relative_profile[a]);
      player.strengths = ranked.slice(0,3);
      player.development_areas = ranked.slice(-2);
      return player;
    });
    const similarities = [];
    for (let i=0; i<players.length; i++) {
      for (let j=i+1; j<players.length; j++) {
        const distance = Math.sqrt(metrics.reduce((sum,metric) => {
          const difference = (players[i].per_90[metric] - players[j].per_90[metric]) / deviations[metric];
          return sum + difference * difference;
        }, 0));
        similarities.push({player_a_id:players[i].player_id, player_b_id:players[j].player_id, similarity:Number((100/(1+distance)).toFixed(1))});
      }
    }
    similarities.sort((a,b) => b.similarity - a.similarity);
    return {players, similarities, benchmark:{minimum_minutes:450, players:benchmark.length, method:'League-relative per-90 profile'}};
  }

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
    let match = pathname.match(/^\/api\/v1\/matches\/(\d+)\/events$/);
    if (match) return clone(data.matchShots[match[1]] || []);
    match = pathname.match(/^\/api\/v1\/matches\/(\d+)\/players$/);
    if (match) return clone(data.matchPlayers[match[1]] || []);
    match = pathname.match(/^\/api\/v1\/matches\/(\d+)$/);
    if (match) return clone(data.matchDetails[match[1]]);
    let player = pathname.match(/^\/api\/v1\/scouting\/players\/(\d+)\/similar$/);
    if (player) return similarPlayers(data, Number(player[1]), url.searchParams);
    player = pathname.match(/^\/api\/v1\/players\/(\d+)\/matches$/);
    if (player) return clone(data.playerLogs[player[1]] || []).slice(0, Number(url.searchParams.get('limit') || 38));
    player = pathname.match(/^\/api\/v1\/players\/(\d+)$/);
    if (player) return clone(data.playerDetails[player[1]]);
    return undefined;
  };
})();
