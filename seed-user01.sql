-- ═══════════════════════════════════════════════════════════════════════
--  CHAKRAVYUH SETU — Direct Officer Provisioning SQL Script
--
--  Account:  user01@gmail.com
--  Password: Test@123
--  Role:     admin (active, Tier 1 - Unit Attribution)
--
--  Paste and Run this in Supabase Dashboard -> SQL Editor -> Run
-- ═══════════════════════════════════════════════════════════════════════

create extension if not exists "pgcrypto";

do $$
declare
  target_email text := 'user01@gmail.com';
  target_pass  text := 'Test@123';
  v_user_id    uuid;
begin
  -- 1. Check if user already exists in auth.users
  select id into v_user_id from auth.users where email = target_email;

  if v_user_id is null then
    v_user_id := gen_random_uuid();

    -- Create user in auth.users with confirmed email and encrypted password
    insert into auth.users (
      instance_id,
      id,
      aud,
      role,
      email,
      encrypted_password,
      email_confirmed_at,
      recovery_sent_at,
      last_sign_in_at,
      raw_app_meta_data,
      raw_user_meta_data,
      created_at,
      updated_at,
      confirmation_token,
      email_change,
      email_change_token_new,
      recovery_token
    ) values (
      '00000000-0000-0000-0000-000000000000',
      v_user_id,
      'authenticated',
      'authenticated',
      target_email,
      crypt(target_pass, gen_salt('bf')),
      now(),
      now(),
      now(),
      '{"provider":"email","providers":["email"]}'::jsonb,
      '{"full_name":"Officer User01","badge_id":"I4C-IND-001","station_code":"CYBER-PS-I4C-DELHI","clearance":"Tier 1 - Unit Attribution"}'::jsonb,
      now(),
      now(),
      '',
      '',
      '',
      ''
    );
  else
    -- Update existing user credentials & ensure confirmed
    update auth.users
    set encrypted_password = crypt(target_pass, gen_salt('bf')),
        email_confirmed_at = coalesce(email_confirmed_at, now()),
        raw_app_meta_data = '{"provider":"email","providers":["email"]}'::jsonb,
        updated_at = now()
    where id = v_user_id;
  end if;

  -- 2. Upsert profile in public.profiles with admin privileges
  insert into public.profiles (
    id,
    email,
    full_name,
    badge_id,
    station_code,
    clearance,
    role,
    status,
    created_at
  ) values (
    v_user_id,
    target_email,
    'Officer User01',
    'I4C-IND-001',
    'CYBER-PS-I4C-DELHI',
    'Tier 1 - Unit Attribution',
    'admin',
    'active',
    now()
  )
  on conflict (id) do update set
    email = excluded.email,
    role = 'admin',
    status = 'active',
    clearance = 'Tier 1 - Unit Attribution';

  raise notice 'Successfully provisioned % with admin role', target_email;
end $$;
