-- Schéma de la plateforme de paiement FICTIVE. Aucune donnée réelle.
-- Un rôle par service, limité à ses propres tables (moindre privilège) :
--   auth_svc    -> auth.users            (lecture, création, mise à jour)
--   payment_svc -> payment.accounts      (lecture, mise à jour du SEUL solde)
--                  payment.transactions  (lecture, insertion ; jamais de modification ni suppression)

REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE ROLE auth_svc LOGIN PASSWORD :'auth_pw' CONNECTION LIMIT 30;
CREATE ROLE payment_svc LOGIN PASSWORD :'pay_pw' CONNECTION LIMIT 30;
GRANT CONNECT ON DATABASE :"dbname" TO auth_svc, payment_svc;

-- ---------- Authentification ----------
CREATE SCHEMA auth;

CREATE TABLE auth.users (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE CHECK (length(username) BETWEEN 1 AND 64),
    password_hash   TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT USAGE ON SCHEMA auth TO auth_svc;
GRANT SELECT, INSERT, UPDATE ON auth.users TO auth_svc;
ALTER ROLE auth_svc SET search_path = auth;

-- ---------- Paiement ----------
CREATE SCHEMA payment;

CREATE TABLE payment.accounts (
    id         BIGINT PRIMARY KEY,
    owner      TEXT NOT NULL,
    label      TEXT NOT NULL,
    balance    NUMERIC(14, 2) NOT NULL CHECK (balance >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX accounts_owner_idx ON payment.accounts (owner);

CREATE TABLE payment.transactions (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_account_id      BIGINT NOT NULL REFERENCES payment.accounts (id),
    destination_account_id BIGINT NOT NULL REFERENCES payment.accounts (id),
    amount                 NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    initiated_by           TEXT NOT NULL,
    idempotency_key        TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_account_id <> destination_account_id),
    UNIQUE (initiated_by, idempotency_key)
);
CREATE INDEX transactions_source_idx ON payment.transactions (source_account_id);
CREATE INDEX transactions_destination_idx ON payment.transactions (destination_account_id);

GRANT USAGE ON SCHEMA payment TO payment_svc;
GRANT SELECT, UPDATE (balance) ON payment.accounts TO payment_svc;
GRANT SELECT, INSERT ON payment.transactions TO payment_svc;
ALTER ROLE payment_svc SET search_path = payment;

-- ---------- Données fictives ----------
INSERT INTO payment.accounts (id, owner, label, balance) VALUES
    (1, 'alice',   'Compte courant Alice (fictif)',            1500.00),
    (2, 'bob',     'Compte courant Bob (fictif)',               750.00),
    (3, 'charlie', 'Compte courant Charlie (fictif)',          2300.00),
    (4, 'probe',   'Compte technique de vérification (fictif)', 1000000.00),
    (5, 'bank',    'Compte de collecte (fictif)',                  0.00);
