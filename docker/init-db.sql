-- Script de inicialização do banco de dados Intellexia
-- Este arquivo é executado automaticamente ao iniciar o container MySQL

-- Garantir que o banco de dados existe
CREATE DATABASE IF NOT EXISTS intellexia;

-- Garantir que o usuário existe com as permissões corretas
CREATE USER IF NOT EXISTS 'intellexia'@'%' IDENTIFIED BY 'intellexia_password_123';

-- Conceder permissões completas ao usuário intellexia no banco intellexia
GRANT ALL PRIVILEGES ON intellexia.* TO 'intellexia'@'%';

-- Conceder permissões adicionais necessárias
GRANT CREATE TEMPORARY TABLES ON intellexia.* TO 'intellexia'@'%';
GRANT LOCK TABLES ON intellexia.* TO 'intellexia'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER ON intellexia.* TO 'intellexia'@'%';

-- Recarregar as permissões
FLUSH PRIVILEGES;

-- Selecionar o banco padrão
USE intellexia;

-- Criar tabelas básicas (opcional - a aplicação pode fazer isso)
-- A aplicação criará as tabelas conforme necessário via ORM (SQLAlchemy)

-- Mensagem de sucesso
SELECT 'Banco Intellexia inicializado com sucesso!' as mensagem;
