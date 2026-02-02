-- Migração: Adiciona coluna fap_vigencia_years à tabela case_benefits
-- Armazena os anos de vigência FAP selecionados (comma-separated)
-- Exemplo: "2019,2020,2021"

ALTER TABLE case_benefits 
ADD COLUMN fap_vigencia_years VARCHAR(500);

-- Comentário de ajuda (SQLite não suporta comentários em ADD COLUMN)
-- Este campo armazena os anos de vigência FAP do benefício separados por vírgula
-- Formato: "2019,2020,2021"
-- Nullable: SIM (pode estar vazio se o benefício não tem vigência FAP)
