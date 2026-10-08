-- Campos Orkavyn — esquema do Supabase (já aplicado no projeto "campos-orkavyn").
-- Guardado aqui para recriar o banco do zero (SQL Editor do Supabase).
--
-- Segurança: RLS ligada e SEM políticas = ninguém lê/escreve as tabelas direto pela API.
-- O app só chama as funções abaixo (RPC), e todas exigem o código de acesso da equipe,
-- guardado apenas como hash SHA-256 em config_app. A exclusão é "suave" (excluido_em).

create table public.observacoes (
  id          bigint generated always as identity primary key,
  criado_em   timestamptz not null default now(),
  data_hora   timestamp   not null,
  observador  text,
  lote        text        not null check (length(btrim(lote)) > 0),
  pasto       text        not null check (length(btrim(pasto)) > 0),
  n_animais   integer     not null check (n_animais between 1 and 5000),
  temperatura numeric(4,1) not null check (temperatura between -5 and 50),
  umidade     numeric(4,1) not null check (umidade between 0 and 100),
  fr          integer     not null check (fr between 5 and 200),
  locomocao   integer     not null check (locomocao between 1 and 5),
  observacoes text,
  excluido_em timestamptz
);
create index observacoes_data_hora_idx on public.observacoes (data_hora desc);
alter table public.observacoes enable row level security;

create table public.config_app (chave text primary key, valor text not null);
alter table public.config_app enable row level security;

create function public.checar_codigo(p_codigo text) returns boolean
language sql stable security definer set search_path = public, pg_temp as $$
  select exists (
    select 1 from public.config_app
    where chave = 'codigo_hash'
      and valor = encode(sha256(convert_to(coalesce(p_codigo, ''), 'utf8')), 'hex')
  );
$$;

create function public.verificar_codigo(p_codigo text) returns boolean
language sql stable security definer set search_path = public, pg_temp as $$
  select public.checar_codigo(p_codigo);
$$;

create function public.listar_observacoes(p_codigo text)
returns table (id bigint, data_hora text, observador text, lote text, pasto text, n_animais integer,
               temperatura numeric, umidade numeric, fr integer, locomocao integer, observacoes text)
language plpgsql stable security definer set search_path = public, pg_temp as $$
begin
  if not public.checar_codigo(p_codigo) then raise exception 'codigo_invalido' using errcode = '28000'; end if;
  return query
    select o.id, to_char(o.data_hora, 'YYYY-MM-DD HH24:MI'), o.observador, o.lote, o.pasto, o.n_animais,
           o.temperatura, o.umidade, o.fr, o.locomocao, o.observacoes
    from public.observacoes o where o.excluido_em is null order by o.data_hora desc, o.id desc;
end $$;

create function public.inserir_varias(p_codigo text, p_linhas jsonb) returns integer
language plpgsql security definer set search_path = public, pg_temp as $$
declare n integer;
begin
  if not public.checar_codigo(p_codigo) then raise exception 'codigo_invalido' using errcode = '28000'; end if;
  insert into public.observacoes (data_hora, observador, lote, pasto, n_animais, temperatura, umidade, fr, locomocao, observacoes)
  select (r.data_hora)::timestamp, nullif(btrim(r.observador), ''), btrim(r.lote), btrim(r.pasto), r.n_animais,
         r.temperatura, r.umidade, r.fr, r.locomocao, nullif(btrim(r.observacoes), '')
  from jsonb_to_recordset(p_linhas) as r(data_hora text, observador text, lote text, pasto text, n_animais int,
       temperatura numeric, umidade numeric, fr int, locomocao int, observacoes text);
  get diagnostics n = row_count;
  return n;
end $$;

create function public.excluir_observacao(p_codigo text, p_id bigint) returns integer
language plpgsql security definer set search_path = public, pg_temp as $$
declare n integer;
begin
  if not public.checar_codigo(p_codigo) then raise exception 'codigo_invalido' using errcode = '28000'; end if;
  update public.observacoes set excluido_em = now() where id = p_id and excluido_em is null;
  get diagnostics n = row_count;
  return n;
end $$;

create function public.apagar_exemplos(p_codigo text, p_observador text) returns integer
language plpgsql security definer set search_path = public, pg_temp as $$
declare n integer;
begin
  if not public.checar_codigo(p_codigo) then raise exception 'codigo_invalido' using errcode = '28000'; end if;
  update public.observacoes set excluido_em = now() where observador = p_observador and excluido_em is null;
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.checar_codigo(text) from public, anon, authenticated;
revoke all on function public.verificar_codigo(text) from public, anon, authenticated;
revoke all on function public.listar_observacoes(text) from public, anon, authenticated;
revoke all on function public.inserir_varias(text, jsonb) from public, anon, authenticated;
revoke all on function public.excluir_observacao(text, bigint) from public, anon, authenticated;
revoke all on function public.apagar_exemplos(text, text) from public, anon, authenticated;
grant execute on function public.verificar_codigo(text) to anon;
grant execute on function public.listar_observacoes(text) to anon;
grant execute on function public.inserir_varias(text, jsonb) to anon;
grant execute on function public.excluir_observacao(text, bigint) to anon;
grant execute on function public.apagar_exemplos(text, text) to anon;

-- Defina o código da equipe (troque o texto; guarda só o hash):
-- insert into public.config_app (chave, valor)
-- values ('codigo_hash', encode(sha256(convert_to('SEU-CODIGO-AQUI', 'utf8')), 'hex'))
-- on conflict (chave) do update set valor = excluded.valor;
