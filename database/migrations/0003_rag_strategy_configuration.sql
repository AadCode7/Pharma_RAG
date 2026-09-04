-- Store the strategy choices used when each document version is created.
-- The implementation can evolve independently from this configuration.

alter table document_versions
  add column if not exists chunking_strategy text not null default 'fixed_size_v1',
  add column if not exists embedding_strategy text not null default 'bge_small',
  add column if not exists embedding_model text not null default 'BAAI/bge-small-en-v1.5';

create index if not exists document_versions_strategy_idx
  on document_versions (chunking_strategy, embedding_strategy);
