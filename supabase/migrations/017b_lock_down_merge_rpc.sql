-- merge_restaurants_atomic must only be callable by service_role.
-- Without this, anon/authenticated PostgREST clients could delete restaurants
-- via POST /rest/v1/rpc/merge_restaurants_atomic.
revoke all on function public.merge_restaurants_atomic(uuid, uuid) from public;
revoke all on function public.merge_restaurants_atomic(uuid, uuid) from anon;
revoke all on function public.merge_restaurants_atomic(uuid, uuid) from authenticated;
grant execute on function public.merge_restaurants_atomic(uuid, uuid) to service_role;
