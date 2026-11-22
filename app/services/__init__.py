"""Serviços de coleta, análise e IA.

Os serviços recebem `settings` (qualquer Mapping, ex.: app.config) e a `session`
do SQLAlchemy por parâmetro — assim rodam em jobs, no seed e em testes sem
depender de request context.
"""
