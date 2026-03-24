-- TiDB Cloud Lead Generation Schema (TiDB Cloud ICP)
-- Apply via: mysql -h HOST -P 4000 -u USER -p < schema.sql
-- Or paste into TiDB Cloud SQL editor

CREATE DATABASE IF NOT EXISTS tidb_leads;
USE tidb_leads;

CREATE TABLE IF NOT EXISTS leads (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    company_name    VARCHAR(255) NOT NULL,
    website         VARCHAR(500),
    country         VARCHAR(100) NOT NULL,
    region          VARCHAR(100) NOT NULL,
    industry        VARCHAR(100),
    description     TEXT,
    tidb_pain       TEXT,
    tidb_use_case   TEXT,
    fit_score       INT CHECK (fit_score BETWEEN 1 AND 10),
    source_url      VARCHAR(500),
    company_size    VARCHAR(50),
    status          VARCHAR(50) DEFAULT 'new',
    created_at      DATETIME DEFAULT NOW(),
    updated_at      DATETIME DEFAULT NOW(),
    geo             VARCHAR(20) DEFAULT 'EMEA',
    UNIQUE KEY leads_company_country_unique (company_name, country)
);

CREATE TABLE IF NOT EXISTS contacts (
    id              INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    lead_id         INT NOT NULL,
    role            VARCHAR(200),
    name            VARCHAR(200),
    linkedin_url    VARCHAR(500),
    email           VARCHAR(200),
    created_at      DATETIME DEFAULT NOW(),
    CONSTRAINT fk_contacts_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_leads_country    ON leads(country);
CREATE INDEX IF NOT EXISTS idx_leads_region     ON leads(region);
CREATE INDEX IF NOT EXISTS idx_leads_fit_score  ON leads(fit_score);
CREATE INDEX IF NOT EXISTS idx_leads_status     ON leads(status);
CREATE INDEX IF NOT EXISTS idx_contacts_lead    ON contacts(lead_id);

CREATE INDEX IF NOT EXISTS idx_leads_geo        ON leads(geo);

-- Migration: run these if upgrading an existing tidb_leads database
-- ALTER TABLE leads ADD COLUMN IF NOT EXISTS company_size VARCHAR(50);
-- ALTER TABLE leads ADD COLUMN IF NOT EXISTS geo VARCHAR(20) DEFAULT 'EMEA';
-- ALTER TABLE leads CHANGE db9_pain tidb_pain TEXT;
-- ALTER TABLE leads CHANGE db9_use_case tidb_use_case TEXT;

-- Backfill geo for existing leads (all current leads are EMEA):
-- UPDATE leads SET geo = 'EMEA' WHERE geo IS NULL;

-- Add embedding and outreach_recommendation columns (if upgrading):
-- ALTER TABLE leads ADD COLUMN embedding              TEXT AFTER status;
-- ALTER TABLE leads ADD COLUMN outreach_recommendation TEXT AFTER embedding;
