(function () {
  const metrics = ['goals', 'xg', 'shots', 'passes', 'carries', 'pressures', 'tackles', 'interceptions'];
  const clone = value => JSON.parse(JSON.stringify(value));

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
    const target = data.scoutingBase.find(player => player.player_id === playerId);
    if (!target) return undefined;
    const candidates = data.scoutingBase.filter(player => player.player_id !== playerId && player.minutes >= minMinutes && player.position === target.position).map(clone);
    const comparison = [...candidates, target];
    const means = Object.fromEntries(metrics.map(metric => [metric, comparison.reduce((sum,p) => sum + p.per_90[metric], 0) / comparison.length]));
    const deviations = Object.fromEntries(metrics.map(metric => {
      const variance = comparison.reduce((sum,p) => sum + Math.pow(p.per_90[metric] - means[metric], 2), 0) / comparison.length;
      return [metric, Math.sqrt(variance) || 1];
    }));
    for (const player of candidates) {
      const distance = Math.sqrt(metrics.reduce((sum,metric) => {
        const difference = (player.per_90[metric] - target.per_90[metric]) / deviations[metric];
        return sum + difference * difference;
      }, 0));
      player.similarity = Number((100 / (1 + distance)).toFixed(1));
    }
    candidates.sort((a,b) => b.similarity - a.similarity);
    return { target: clone(target), similar_players: candidates.slice(0, limit) };
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
