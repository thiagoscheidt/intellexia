SET FOREIGN_KEY_CHECKS = 0;

UPDATE fap_contestation_judgment_reports
SET
status = 'pending',
error_message = NULL,
processed_at = NULL,
imported_benefits_count = 0,
updated_at = UTC_TIMESTAMP();

TRUNCATE TABLE benefit_fap_source_history;
TRUNCATE TABLE benefit_manual_history;

TRUNCATE TABLE fap_contestation_cat_source_history;
TRUNCATE TABLE fap_contestation_cat_manual_history;

TRUNCATE TABLE fap_contestation_payroll_mass_source_history;
TRUNCATE TABLE fap_contestation_payroll_mass_manual_history;

TRUNCATE TABLE fap_contestation_employment_link_source_history;
TRUNCATE TABLE fap_contestation_employment_link_manual_history;

TRUNCATE TABLE fap_contestation_turnover_rate_source_history;
TRUNCATE TABLE fap_contestation_turnover_rate_manual_history;

TRUNCATE TABLE benefits;
TRUNCATE TABLE fap_contestation_cats;
TRUNCATE TABLE fap_contestation_payroll_masses;
TRUNCATE TABLE fap_contestation_employment_links;
TRUNCATE TABLE fap_contestation_turnover_rates;
TRUNCATE TABLE fap_vigencia_cnpjs;
TRUNCATE TABLE fap_auto_imported_contestacoes;

TRUNCATE TABLE fap_web_contestacao_change_history;
TRUNCATE TABLE fap_web_contestacoes;
TRUNCATE TABLE fap_web_procuracoes;
TRUNCATE TABLE fap_companies;

SET FOREIGN_KEY_CHECKS = 1;