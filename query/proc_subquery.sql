LEFT JOIN (
  select
    procedurecode_id,
    count
  from
    public.orders_procedure
  where
    type = '{type}'
    and office_id = {office_id}
    and start_date = '{day_from}'
) as {tablename} ON A.procedurecode_id = {tablename}.procedurecode_id
