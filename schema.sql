CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS client (
  client_id UUID PRIMARY KEY,
  tin TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hold_type') THEN
    CREATE TYPE hold_type AS ENUM ('FRAUD_SUSPECT', 'INCORRECT_BENEFICIARY_DETAILS');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hold_status') THEN
    CREATE TYPE hold_status AS ENUM ('ACTIVE', 'RELEASED', 'EXPIRED');
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS payment_hold (
  hold_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_id UUID NOT NULL REFERENCES client(client_id),
  type hold_type NOT NULL,
  status hold_status NOT NULL DEFAULT 'ACTIVE',
  comment TEXT,
  source TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT NOT NULL,
  expires_at TIMESTAMPTZ,
  released_at TIMESTAMPTZ,
  released_by TEXT,
  release_reason TEXT,
  idempotency_key TEXT NOT NULL,
  CONSTRAINT unique_idem UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_payment_hold_client_active
  ON payment_hold (client_id)
  WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_payment_hold_client_type_active
  ON payment_hold (client_id, type)
  WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_payment_hold_expires
  ON payment_hold (expires_at)
  WHERE status = 'ACTIVE' AND expires_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS payment_hold_audit (
  audit_id BIGSERIAL PRIMARY KEY,
  hold_id UUID NOT NULL,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  changed_by TEXT NOT NULL,
  old_status hold_status,
  new_status hold_status,
  note TEXT
);

CREATE OR REPLACE VIEW v_client_hold_status AS
SELECT
  c.client_id,
  EXISTS (SELECT 1 FROM payment_hold ph WHERE ph.client_id = c.client_id AND ph.status = 'ACTIVE') AS blocked,
  CASE
    WHEN EXISTS (SELECT 1 FROM payment_hold ph WHERE ph.client_id = c.client_id AND ph.status = 'ACTIVE' AND ph.type = 'FRAUD_SUSPECT')
      THEN 'FRAUD'
    WHEN EXISTS (SELECT 1 FROM payment_hold ph WHERE ph.client_id = c.client_id AND ph.status = 'ACTIVE')
      THEN 'NON_FRAUD'
    ELSE 'NONE'
  END AS kind
FROM client c;

INSERT INTO client (client_id, tin) VALUES
('7d2b2b7a-2c0c-4f7c-8a84-2f4a3f686e55','7701234567')
ON CONFLICT DO NOTHING;