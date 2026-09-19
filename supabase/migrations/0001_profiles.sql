-- Stepping-stone identity row for the Android client.
-- Conversation sessions are not created here.

create table if not exists public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    discord_id text,
    username text,
    avatar_url text,
    created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "Users can read own profile"
    on public.profiles
    for select
    using (auth.uid() = id);

create policy "Users can update own profile"
    on public.profiles
    for update
    using (auth.uid() = id)
    with check (auth.uid() = id);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, discord_id, username, avatar_url)
    values (
        new.id,
        coalesce(
            new.raw_user_meta_data ->> 'provider_id',
            new.raw_user_meta_data ->> 'sub'
        ),
        coalesce(
            new.raw_user_meta_data ->> 'full_name',
            new.raw_user_meta_data ->> 'name',
            new.raw_user_meta_data ->> 'preferred_username',
            new.raw_user_meta_data -> 'custom_claims' ->> 'global_name'
        ),
        coalesce(
            new.raw_user_meta_data ->> 'avatar_url',
            new.raw_user_meta_data ->> 'picture'
        )
    );
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row
    execute function public.handle_new_user();

grant select, update on public.profiles to authenticated;
