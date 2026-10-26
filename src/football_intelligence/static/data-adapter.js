(function () {
  const metrics = ['goals', 'xg', 'shots', 'passes', 'carries', 'pressures', 'tackles', 'interceptions'];
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
    player = pathname.match(/^\/api\/v1\/scouting\/players\/(\d+)\/replacements$/);
    if (player) return replacementPlayers(data, Number(player[1]), url.searchParams);
    player = pathname.match(/^\/api\/v1\/players\/(\d+)\/matches$/);
    if (player) return clone(data.playerLogs[player[1]] || []).slice(0, Number(url.searchParams.get('limit') || 38));
    player = pathname.match(/^\/api\/v1\/players\/(\d+)$/);
    if (player) return clone(data.playerDetails[player[1]]);
    return undefined;
  };
})();
