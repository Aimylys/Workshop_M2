-- Données 100% fictives (aucune donnée bancaire réelle)
CREATE TABLE accounts (
    id       SERIAL PRIMARY KEY,
    owner    TEXT NOT NULL,
    balance  NUMERIC(12,2) NOT NULL DEFAULT 1000.00
);

CREATE TABLE transactions (
    id         SERIAL PRIMARY KEY,
    from_acc   INTEGER REFERENCES accounts(id),
    to_acc     INTEGER REFERENCES accounts(id),
    amount     NUMERIC(12,2) NOT NULL,
    status     TEXT NOT NULL DEFAULT 'OK',
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE users (
    id       SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    -- mot de passe fictif en clair UNIQUEMENT pour la démo pédagogique
    password TEXT NOT NULL
);

INSERT INTO accounts (owner, balance) VALUES
    ('alice', 5000), ('bob', 3000), ('carol', 7000), ('dave', 1200);

INSERT INTO users (username, password) VALUES
    ('alice', 'demo123'), ('bob', 'demo123'), ('admin', 'demo123');
