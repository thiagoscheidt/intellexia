-- Ajuste o banco conforme necessário
CREATE DATABASE IF NOT EXISTS advogado_fap
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE advogado_fap;

-- ========================
-- Tabela: clients (Autora)
-- ========================
CREATE TABLE `clients` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NOT NULL,
  `cnpj` VARCHAR(20) NOT NULL,
  `street` VARCHAR(255) NULL,
  `number` VARCHAR(20) NULL,
  `district` VARCHAR(150) NULL,
  `city` VARCHAR(150) NULL,
  `state` VARCHAR(50) NULL,
  `zip_code` VARCHAR(20) NULL,
  `has_branches` TINYINT(1) NOT NULL DEFAULT 0,
  `branches_description` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  INDEX `idx_clients_cnpj` (`cnpj`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================
-- Tabela: courts (Varas)
-- ========================
CREATE TABLE `courts` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `section` VARCHAR(255) NULL,      -- Seção Judiciária de XX
  `vara_name` VARCHAR(255) NULL,    -- Ex: "1ª Vara Federal de XXX"
  `city` VARCHAR(150) NULL,
  `state` VARCHAR(50) NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================
-- Tabela: lawyers (Advogados)
-- ========================
CREATE TABLE `lawyers` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(255) NOT NULL,
  `oab_number` VARCHAR(50) NOT NULL,
  `email` VARCHAR(255) NULL,
  `phone` VARCHAR(50) NULL,
  `is_default_for_publications` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_lawyers_oab` (`oab_number`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ========================
-- Tabela: cases (Casos)
-- ========================
CREATE TABLE `cases` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `client_id` BIGINT UNSIGNED NOT NULL,
  `court_id` BIGINT UNSIGNED NULL,
  `title` VARCHAR(255) NOT NULL,
  `case_type` VARCHAR(50) NOT NULL,          -- ex: fap_trajeto
  `fap_start_year` SMALLINT UNSIGNED NULL,   -- ex: 2016
  `fap_end_year` SMALLINT UNSIGNED NULL,     -- ex: 2022
  `facts_summary` TEXT NULL,
  `thesis_summary` TEXT NULL,
  `prescription_summary` TEXT NULL,
  `value_cause` DECIMAL(15,2) NULL,
  `status` VARCHAR(30) NOT NULL DEFAULT 'draft',
  `filing_date` DATE NULL,                   -- data de ajuizamento (se existir)
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_cases_client_id` (`client_id`),
  KEY `idx_cases_court_id` (`court_id`),
  CONSTRAINT `fk_cases_clients`
    FOREIGN KEY (`client_id`) REFERENCES `clients`(`id`)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_cases_courts`
    FOREIGN KEY (`court_id`) REFERENCES `courts`(`id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================================
-- Tabela: case_lawyers (Caso x Adv.)
-- ==================================
CREATE TABLE `case_lawyers` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id` BIGINT UNSIGNED NOT NULL,
  `lawyer_id` BIGINT UNSIGNED NOT NULL,
  `role` VARCHAR(50) NULL,  -- ex: responsavel, publicacoes, auxiliar
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_case_lawyers_case_id` (`case_id`),
  KEY `idx_case_lawyers_lawyer_id` (`lawyer_id`),
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
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id` BIGINT UNSIGNED NOT NULL,
  `competence_month` TINYINT UNSIGNED NOT NULL, -- 1 a 12
  `competence_year` SMALLINT UNSIGNED NOT NULL,
  `status` ENUM('prescribed', 'valid') NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_case_competences_case_id` (`case_id`),
  CONSTRAINT `fk_case_competences_cases`
    FOREIGN KEY (`case_id`) REFERENCES `cases`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==================================
-- Tabela: case_benefits (Benefícios)
-- ==================================
CREATE TABLE `case_benefits` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id` BIGINT UNSIGNED NOT NULL,
  `benefit_number` VARCHAR(50) NOT NULL,     -- ex: 6239386921
  `benefit_type` VARCHAR(10) NOT NULL,       -- ex: B91, B94
  `insured_name` VARCHAR(255) NOT NULL,
  `insured_nit` VARCHAR(50) NULL,
  `accident_date` DATE NULL,
  `accident_company_name` VARCHAR(255) NULL, -- empresa em que ocorreu o acidente
  `error_reason` VARCHAR(50) NULL,           -- ex: trajeto, outra_empresa, duplicidade
  `notes` TEXT NULL,
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
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id` BIGINT UNSIGNED NOT NULL,
  `related_benefit_id` BIGINT UNSIGNED NULL,
  `original_filename` VARCHAR(255) NOT NULL,
  `file_path` VARCHAR(500) NOT NULL,
  `document_type` VARCHAR(50) NOT NULL,      -- cat, laudo_medico, infben, conbas, tela_fap, etc.
  `description` TEXT NULL,
  `use_in_ai` TINYINT(1) NOT NULL DEFAULT 1,
  `uploaded_by_user_id` BIGINT UNSIGNED NULL, -- se depois você tiver tabela de usuários
  `uploaded_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_documents_case_id` (`case_id`),
  KEY `idx_documents_related_benefit_id` (`related_benefit_id`),
  CONSTRAINT `fk_documents_cases`
    FOREIGN KEY (`case_id`) REFERENCES `cases`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_documents_case_benefits`
    FOREIGN KEY (`related_benefit_id`) REFERENCES `case_benefits`(`id`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
