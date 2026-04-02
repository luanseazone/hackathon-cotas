-- =============================================================
-- Hackathon Cotas Seazone — Schema Supabase
-- Rodar no SQL Editor do Supabase Dashboard
-- =============================================================

-- ─── TABELAS DE DADOS (seed via Python) ───────────────────────

CREATE TABLE IF NOT EXISTS investidores (
  id            BIGINT PRIMARY KEY,
  nome          TEXT,
  cpf_cnpj      TEXT UNIQUE NOT NULL,
  email         TEXT,
  phone         TEXT,
  end_cidade    TEXT,
  end_estado    TEXT,
  created_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS empreendimentos (
  id            BIGINT PRIMARY KEY,
  nome          TEXT,
  cidade        TEXT,
  estado        TEXT,
  created_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS unidades (
  id                  BIGINT PRIMARY KEY,
  empreendimento_id   BIGINT REFERENCES empreendimentos(id),
  codigo              TEXT,
  area                NUMERIC,
  andar               TEXT,
  status              TEXT,
  created_at          TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS descricao_unidades (
  id                  BIGINT PRIMARY KEY,
  unidade_id          BIGINT REFERENCES unidades(id),
  mezanino            BOOLEAN,
  area_mezanino       NUMERIC,
  sacada_terraco      BOOLEAN,
  area_sacada_terraco NUMERIC,
  garden              BOOLEAN,
  area_garden         NUMERIC,
  vista_mar           BOOLEAN,
  posicao_solar       TEXT,
  pcd                 BOOLEAN,
  capacidade          INTEGER
);

CREATE TABLE IF NOT EXISTS contratos (
  id                BIGINT PRIMARY KEY,
  unidade_id        BIGINT REFERENCES unidades(id),
  investidor_id     BIGINT REFERENCES investidores(id),
  participacao      NUMERIC,
  data_assinatura   DATE,
  status            TEXT,
  created_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS resumo_financeiro (
  id              BIGINT PRIMARY KEY,  -- == unidade_id
  unidade_id      BIGINT UNIQUE REFERENCES unidades(id),
  valor_pago      NUMERIC DEFAULT 0,
  valor_pendente  NUMERIC DEFAULT 0
);

CREATE TABLE IF NOT EXISTS historico_pagamentos (
  id          BIGSERIAL PRIMARY KEY,
  unidade_id  BIGINT REFERENCES unidades(id),
  mes         DATE NOT NULL,
  valor_pago  NUMERIC,
  quantidade  INTEGER,
  UNIQUE (unidade_id, mes)
);

-- ─── MARKETPLACE ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS marketplace_listings (
  id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  unidade_id      BIGINT UNIQUE REFERENCES unidades(id),
  investidor_id   BIGINT REFERENCES investidores(id),
  preco_sugerido  NUMERIC,
  preco_final     NUMERIC,
  roi_calculado   NUMERIC,
  descricao       TEXT,
  status          TEXT DEFAULT 'ativo' CHECK (status IN ('ativo', 'vendido', 'retirado')),
  created_at      TIMESTAMPTZ DEFAULT now(),
  updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ─── AUTH: mapear cpf_cnpj → investidor ───────────────────────
-- Supabase Auth usa {cpf_cnpj}@seazone.internal como email fictício.
-- Esta view cruza auth.users com investidores.

CREATE OR REPLACE VIEW investidor_atual AS
  SELECT i.*
  FROM investidores i
  JOIN auth.users u ON u.email = i.cpf_cnpj || '@seazone.internal'
  WHERE u.id = auth.uid();

-- ─── RLS ──────────────────────────────────────────────────────

ALTER TABLE investidores          ENABLE ROW LEVEL SECURITY;
ALTER TABLE empreendimentos       ENABLE ROW LEVEL SECURITY;
ALTER TABLE unidades              ENABLE ROW LEVEL SECURITY;
ALTER TABLE descricao_unidades    ENABLE ROW LEVEL SECURITY;
ALTER TABLE contratos             ENABLE ROW LEVEL SECURITY;
ALTER TABLE resumo_financeiro     ENABLE ROW LEVEL SECURITY;
ALTER TABLE historico_pagamentos  ENABLE ROW LEVEL SECURITY;
ALTER TABLE marketplace_listings  ENABLE ROW LEVEL SECURITY;

-- Investidor vê apenas o próprio perfil
CREATE POLICY "investidor_proprio" ON investidores
  FOR SELECT USING (
    cpf_cnpj || '@seazone.internal' = (SELECT email FROM auth.users WHERE id = auth.uid())
  );

-- Empreendimentos são públicos (leitura)
CREATE POLICY "empreendimentos_publicos" ON empreendimentos
  FOR SELECT USING (true);

-- Unidades: investidor vê apenas as suas (via contrato)
CREATE POLICY "unidades_do_investidor" ON unidades
  FOR SELECT USING (
    id IN (
      SELECT c.unidade_id FROM contratos c
      JOIN investidores i ON i.id = c.investidor_id
      WHERE i.cpf_cnpj || '@seazone.internal' = (SELECT email FROM auth.users WHERE id = auth.uid())
    )
  );

-- Descrição de unidades: mesmo filtro de unidades
CREATE POLICY "descricao_do_investidor" ON descricao_unidades
  FOR SELECT USING (
    unidade_id IN (
      SELECT c.unidade_id FROM contratos c
      JOIN investidores i ON i.id = c.investidor_id
      WHERE i.cpf_cnpj || '@seazone.internal' = (SELECT email FROM auth.users WHERE id = auth.uid())
    )
  );

-- Contratos: investidor vê apenas os seus
CREATE POLICY "contratos_do_investidor" ON contratos
  FOR SELECT USING (
    investidor_id IN (
      SELECT id FROM investidores
      WHERE cpf_cnpj || '@seazone.internal' = (SELECT email FROM auth.users WHERE id = auth.uid())
    )
  );

-- Resumo financeiro: mesma regra de unidades
CREATE POLICY "resumo_do_investidor" ON resumo_financeiro
  FOR SELECT USING (
    unidade_id IN (
      SELECT c.unidade_id FROM contratos c
      JOIN investidores i ON i.id = c.investidor_id
      WHERE i.cpf_cnpj || '@seazone.internal' = (SELECT email FROM auth.users WHERE id = auth.uid())
    )
  );

-- Histórico de pagamentos: mesma regra
CREATE POLICY "historico_do_investidor" ON historico_pagamentos
  FOR SELECT USING (
    unidade_id IN (
      SELECT c.unidade_id FROM contratos c
      JOIN investidores i ON i.id = c.investidor_id
      WHERE i.cpf_cnpj || '@seazone.internal' = (SELECT email FROM auth.users WHERE id = auth.uid())
    )
  );

-- Marketplace: leitura pública (vitrine), escrita apenas pelo dono
CREATE POLICY "marketplace_leitura_publica" ON marketplace_listings
  FOR SELECT USING (status = 'ativo');

CREATE POLICY "marketplace_escrita_proprio" ON marketplace_listings
  FOR ALL USING (
    investidor_id IN (
      SELECT id FROM investidores
      WHERE cpf_cnpj || '@seazone.internal' = (SELECT email FROM auth.users WHERE id = auth.uid())
    )
  );

-- ─── FUNÇÃO: criar usuário auth a partir de cpf_cnpj ──────────
-- Chamar via service role após seed dos investidores.
-- Senha padrão = os 8 primeiros dígitos do CPF/CNPJ (apenas números).

CREATE OR REPLACE FUNCTION criar_usuario_investidor(p_cpf_cnpj TEXT)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_email TEXT;
  v_senha TEXT;
  v_investidor_id BIGINT;
BEGIN
  SELECT id INTO v_investidor_id FROM investidores WHERE cpf_cnpj = p_cpf_cnpj;
  IF v_investidor_id IS NULL THEN RETURN; END IF;

  v_email := p_cpf_cnpj || '@seazone.internal';
  v_senha := LEFT(REGEXP_REPLACE(p_cpf_cnpj, '[^0-9]', '', 'g'), 8);

  -- Inserir em auth.users se não existir
  INSERT INTO auth.users (
    instance_id, id, aud, role, email, encrypted_password,
    email_confirmed_at, created_at, updated_at,
    raw_app_meta_data, raw_user_meta_data, is_super_admin
  )
  SELECT
    '00000000-0000-0000-0000-000000000000',
    gen_random_uuid(),
    'authenticated',
    'authenticated',
    v_email,
    crypt(v_senha, gen_salt('bf')),
    now(), now(), now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    jsonb_build_object('investidor_id', v_investidor_id),
    false
  WHERE NOT EXISTS (SELECT 1 FROM auth.users WHERE email = v_email);
END;
$$;

-- Criar usuários para todos os investidores seedados
-- (rodar após seed_script.py)
-- SELECT criar_usuario_investidor(cpf_cnpj) FROM investidores;
