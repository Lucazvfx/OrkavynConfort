# Campos Orkavyn — Painel de Conforto do Rebanho

Painel analítico (Streamlit) que cruza clima (ITU) com observação clínica (frequência
respiratória e locomoção) para separar estresse térmico de problema sanitário.

## Rodar

```
pip install -r requirements.txt
streamlit run app.py
```

## Dois modos de dados (automático)

| Modo | Quando | Para quê |
|---|---|---|
| **SQLite local** | sem configuração | testar em um aparelho só |
| **Supabase** | `SUPABASE_URL` e `SUPABASE_KEY` configurados | vários celulares, dados compartilhados |

Para o modo Supabase, copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml`
(ou cole no campo *Secrets* do Streamlit Community Cloud) e preencha a URL e a chave **publicável**.
O esquema do banco está em `supabase/schema.sql`. Cada celular digita o **código da fazenda** uma vez.

Segurança: as tabelas têm RLS e nenhuma política; o app só usa funções do banco que exigem o código
da equipe (guardado como hash). A exclusão é "suave" (o registro fica guardado com `excluido_em`).

## Estrutura

```
app.py              ponto de entrada
orkavyn/config.py   limiares, limites e cores
orkavyn/db.py       backend: SQLite e Supabase
orkavyn/motor.py    motor de análise cruzada (funções puras)
orkavyn/ui.py       frontend: estilo e abas
assets/             logo e foto
supabase/schema.sql esquema do banco compartilhado
```
