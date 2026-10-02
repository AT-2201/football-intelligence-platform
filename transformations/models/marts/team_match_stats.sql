with event_stats as (
    select
        match_id,
        team_id,
        count(*) filter (where type_name = 'Shot') as shots,
        sum(shot_xg) filter (where type_name = 'Shot') as xg,
        count(*) filter (where type_name = 'Pass') as passes,
        count(*) filter (
            where type_name = 'Pass' and pass_outcome_name is null
        ) as completed_passes
    from {{ ref('stg_events') }}
    where team_id is not null
    group by 1, 2
)
select * from event_stats

