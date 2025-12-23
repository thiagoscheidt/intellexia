-- Ajuste o banco conforme necessário
CREATE DATABASE IF NOT EXISTS intellexia
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE intellexia;

-- ========================
-- Tabela: clients (Autora)
-- ========================
CREATE TABLE `clients` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,  -- Identificador único da empresa (PK)
  `name` VARCHAR(255) NOT NULL,                  -- Razão social da empresa
  `cnpj` VARCHAR(20) NOT NULL,                   -- CNPJ da empresa
  `street` VARCHAR(255) NULL,                    -- Rua do endereço
  `number` VARCHAR(20) NULL,                     -- Número do endereço
  `district` VARCHAR(150) NULL,                  -- Bairro
  `city` VARCHAR(150) NULL,                      -- Cidade
  `state` VARCHAR(50) NULL,                      -- Estado (UF)
  `zip_code` VARCHAR(20) NULL,                   -- CEP
  `has_branches` TINYINT(1) NOT NULL DEFAULT 0,  -- Indica se possui filiais (0 = não, 1 = sim)
  `branches_description` TEXT NULL,              -- Texto contendo endereços das filiais
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,                    -- Data de criação
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, -- Última atualização
  PRIMARY KEY (`id`),                            -- Define chave primária
  INDEX `idx_clients_cnpj` (`cnpj`)              -- Índice para busca rápida pelo CNPJ
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================
-- Tabela: courts (Varas)
-- ========================
CREATE TABLE `courts` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,  -- Identificador único da vara
  `section` VARCHAR(255) NULL,                   -- Nome da seção judiciária (ex.: "Seção Judiciária de SC")
  `vara_name` VARCHAR(255) NULL,                 -- Nome/descrição da vara (ex.: "1ª Vara Federal de Blumenau")
  `city` VARCHAR(150) NULL,                      -- Cidade da vara
  `state` VARCHAR(50) NULL,                      -- Estado (UF)
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,                     -- Data de criação
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, -- Última atualização
  PRIMARY KEY (`id`)                             -- Chave primária
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================
-- Tabela: lawyers (Advogados)
-- ========================
CREATE TABLE `lawyers` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,  -- ID do advogado
  `name` VARCHAR(255) NOT NULL,                  -- Nome completo
  `oab_number` VARCHAR(50) NOT NULL,             -- Número da OAB
  `email` VARCHAR(255) NULL,                     -- Email profissional
  `phone` VARCHAR(50) NULL,                      -- Telefone
  `is_default_for_publications` TINYINT(1) NOT NULL DEFAULT 0, -- 1 = advogado padrão para publicações
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,                     -- Criado em
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, -- Atualizado em
  PRIMARY KEY (`id`),                            -- Chave primária
  UNIQUE KEY `uniq_lawyers_oab` (`oab_number`)   -- Não permite OAB duplicada
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================
-- Tabela: cases (Casos)
-- ========================
CREATE TABLE `cases` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,   -- ID do caso
  `client_id` BIGINT UNSIGNED NOT NULL,           -- FK da empresa autora
  `court_id` BIGINT UNSIGNED NULL,                -- FK da vara judicial
  `title` VARCHAR(255) NOT NULL,                  -- Título do caso
  `case_type` VARCHAR(50) NOT NULL,               -- Tipo de caso (ex.: fap_trajeto)
  `fap_start_year` SMALLINT UNSIGNED NULL,        -- Ano inicial da revisão FAP
  `fap_end_year` SMALLINT UNSIGNED NULL,          -- Ano final da revisão FAP
  `facts_summary` TEXT NULL,                      -- Fatos resumidos do caso
  `thesis_summary` TEXT NULL,                     -- Teses jurídicas aplicadas
  `prescription_summary` TEXT NULL,               -- Informações sobre prescrição
  `value_cause` DECIMAL(15,2) NULL,               -- Valor da causa (R$)
  `status` VARCHAR(30) NOT NULL DEFAULT 'draft',  -- Status do caso
  `filing_date` DATE NULL,                        -- Data de ajuizamento
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,                     -- Criado em
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, -- Atualizado em
  PRIMARY KEY (`id`),
  KEY `idx_cases_client_id` (`client_id`),         -- Índice da FK client_id
  KEY `idx_cases_court_id` (`court_id`),           -- Índice da FK court_id
  CONSTRAINT `fk_cases_clients`
    FOREIGN KEY (`client_id`) REFERENCES `clients`(`id`) -- Relaciona cliente
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_cases_courts`
    FOREIGN KEY (`court_id`) REFERENCES `courts`(`id`)   -- Relaciona vara
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================================
-- Tabela: case_lawyers (Caso x Adv.)
-- ==================================
CREATE TABLE `case_lawyers` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,  -- ID da ligação
  `case_id` BIGINT UNSIGNED NOT NULL,            -- FK do caso
  `lawyer_id` BIGINT UNSIGNED NOT NULL,          -- FK do advogado
  `role` VARCHAR(50) NULL,                       -- Função (responsável, publicações…)
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,                     -- Criado em
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, -- Atualizado em
  PRIMARY KEY (`id`),
  KEY `idx_case_lawyers_case_id` (`case_id`),     -- Índice da FK case_id
  KEY `idx_case_lawyers_lawyer_id` (`lawyer_id`), -- Índice da FK lawyer_id
  CONSTRAINT `fk_case_lawyers_cases`
    FOREIGN KEY (`case_id`) REFERENCES `cases`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_case_lawyers_lawyers`
    FOREIGN KEY (`lawyer_id`) REFERENCES `lawyers`(`id`)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =====================================
-- Tabela opcional: case_competences
-- =====================================
CREATE TABLE `case_competences` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, -- ID da competência
  `case_id` BIGINT UNSIGNED NOT NULL,           -- FK do caso
  `competence_month` TINYINT UNSIGNED NOT NULL, -- Mês (1 a 12)
  `competence_year` SMALLINT UNSIGNED NOT NULL, -- Ano
  `status` ENUM('prescribed', 'valid') NOT NULL, -- Situação da competência
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,                     -- Criado
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, -- Atualizado
  PRIMARY KEY (`id`),
  KEY `idx_case_competences_case_id` (`case_id`), -- Índice FK
  CONSTRAINT `fk_case_competences_cases`
    FOREIGN KEY (`case_id`) REFERENCES `cases`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================================
-- Tabela: case_benefits (Benefícios)
-- ==================================
CREATE TABLE `case_benefits` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,   -- ID do benefício
  `case_id` BIGINT UNSIGNED NOT NULL,             -- FK do caso
  `benefit_number` VARCHAR(50) NOT NULL,          -- Número do benefício
  `benefit_type` VARCHAR(10) NOT NULL,            -- Tipo (B91, B94)
  `insured_name` VARCHAR(255) NOT NULL,           -- Nome do segurado
  `insured_nit` VARCHAR(50) NULL,                 -- NIT/PIS do segurado
  `accident_date` DATE NULL,                      -- Data do acidente
  `accident_company_name` VARCHAR(255) NULL,      -- Empresa onde foi o acidente
  `error_reason` VARCHAR(50) NULL,                -- Motivo da contestação
  `notes` TEXT NULL,                              -- Observações adicionais
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_case_benefits_case_id` (`case_id`),
  KEY `idx_case_benefits_benefit_number` (`benefit_number`),
  CONSTRAINT `fk_case_benefits_cases`
    FOREIGN KEY (`case_id`) REFERENCES `cases`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =========================
-- Tabela: documents (Docs)
-- =========================
CREATE TABLE `documents` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,       -- ID do documento
  `case_id` BIGINT UNSIGNED NOT NULL,                 -- FK do caso
  `related_benefit_id` BIGINT UNSIGNED NULL,          -- FK opcional para benefício relacionado
  `original_filename` VARCHAR(255) NOT NULL,          -- Nome original do arquivo
  `file_path` VARCHAR(500) NOT NULL,                  -- Caminho onde o arquivo é salvo
  `document_type` VARCHAR(50) NOT NULL,               -- Tipo (cat, laudo_medico, infben, etc.)
  `description` TEXT NULL,                            -- Descrição livre
  `use_in_ai` TINYINT(1) NOT NULL DEFAULT 1,          -- 1 = IA pode usar / 0 = ignorar
  
  -- Campos para análise de IA
  `ai_summary` TEXT NULL,                             -- Resumo gerado pela IA sobre informações importantes
  `ai_processed_at` DATETIME NULL,                    -- Data/hora do processamento pela IA
  `ai_status` VARCHAR(20) NOT NULL DEFAULT 'pending', -- Status: pending, processing, completed, error
  `ai_error_message` TEXT NULL,                       -- Mensagem de erro caso o processamento falhe
  
  `uploaded_by_user_id` BIGINT UNSIGNED NULL,         -- FK de usuário (no futuro)
  `uploaded_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, -- Data upload
  PRIMARY KEY (`id`),
  KEY `idx_documents_case_id` (`case_id`),
  KEY `idx_documents_related_benefit_id` (`related_benefit_id`),
  KEY `idx_documents_ai_status` (`ai_status`),        -- Índice para buscar documentos por status de IA
  CONSTRAINT `fk_documents_cases`
    FOREIGN KEY (`case_id`) REFERENCES `cases`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_documents_case_benefits`
    FOREIGN KEY (`related_benefit_id`) REFERENCES `case_benefits`(`id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =========================
-- Tabela: petitions (Petições Geradas pela IA)
-- =========================
CREATE TABLE `petitions` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,       -- ID da petição
  `case_id` BIGINT UNSIGNED NOT NULL,                 -- FK do caso
  `version` INT NOT NULL,                             -- Número da versão (1, 2, 3...)
  `title` VARCHAR(255) NOT NULL,                      -- Título da petição
  `content` TEXT NOT NULL,                            -- Conteúdo completo da petição
  
  -- Metadados da geração
  `generated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, -- Data/hora da geração
  `generated_by_user_id` BIGINT UNSIGNED NULL,        -- FK de usuário (futuro)
  
  -- Status da geração
  `status` VARCHAR(20) NOT NULL DEFAULT 'completed',  -- pending, processing, completed, error
  `error_message` TEXT NULL,                          -- Mensagem de erro caso falhe
  
  -- Contexto usado na geração
  `context_summary` TEXT NULL,                        -- Resumo do contexto usado
  
  PRIMARY KEY (`id`),
  KEY `idx_petitions_case_id` (`case_id`),
  KEY `idx_petitions_version` (`case_id`, `version`), -- Índice composto para buscar versões de um caso
  CONSTRAINT `fk_petitions_cases`
    FOREIGN KEY (`case_id`) REFERENCES `cases`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
