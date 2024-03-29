select
  B.proccode,
  B.descript,
  {sub_counts}
from
  public.orders_procedure A {sub_joins}
  left join public.orders_procedurecode B on B.id = A.procedurecode_id
where
  A.type = '{type}'
  and A.office_id = {office_id}
  and A.start_date > '{day_from}'
  and A.start_date < '{day_to}'
  and category in {proc_category}
GROUP BY
  B.proccode,
  B.descript,
  B.category,
  A.procedurecode_id,
  {sub_counts}
ORDER BY
  A.procedurecode_id
LIMIT
  {limit}
