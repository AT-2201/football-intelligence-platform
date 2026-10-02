select
    event_id,
    match_id,
    event_index,
    period,
    minute,
    second,
    type_name,
    team_id,
    player_id,
    possession_team_id,
    pass_outcome_name,
    shot_outcome_name,
    coalesce(shot_statsbomb_xg, 0) as shot_xg
from {{ source('app', 'events') }}

