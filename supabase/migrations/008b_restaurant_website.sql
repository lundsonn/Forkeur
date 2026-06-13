alter table restaurants
  add column if not exists website text,
  add column if not exists order_url text;
