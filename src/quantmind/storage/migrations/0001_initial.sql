-- 初期スキーマ。全テーブルに最低限の列を確保する。
-- DuckDB は CREATE TABLE IF NOT EXISTS 対応。

CREATE TABLE IF NOT EXISTS stocks_master (
    code VARCHAR PRIMARY KEY,                  -- 4桁の証券コード
    name VARCHAR,
    market VARCHAR,                            -- prime / standard / growth
    sector VARCHAR,
    market_cap_jpy BIGINT,                     -- スナップショット時点の時価総額(円)
    snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_daily (
    code VARCHAR NOT NULL,
    date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    adj_close DOUBLE,
    volume BIGINT,
    source VARCHAR,                            -- yfinance / stooq / jquants
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS disclosures (
    id VARCHAR PRIMARY KEY,                    -- ソースごと一意ID
    code VARCHAR,
    source VARCHAR NOT NULL,                   -- tdnet / edinet
    doc_type VARCHAR,                          -- earnings / forecast_revision / m_a / yuho ...
    title VARCHAR,
    disclosed_at TIMESTAMP NOT NULL,
    url VARCHAR,
    body_text TEXT,
    raw_json JSON,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_disclosures_code_date ON disclosures(code, disclosed_at);

CREATE TABLE IF NOT EXISTS financials (
    code VARCHAR NOT NULL,
    fiscal_period VARCHAR NOT NULL,            -- YYYYQn / YYYYFY
    revenue DOUBLE,
    operating_income DOUBLE,
    net_income DOUBLE,
    total_assets DOUBLE,
    total_equity DOUBLE,
    raw_json JSON,
    PRIMARY KEY (code, fiscal_period)
);

CREATE TABLE IF NOT EXISTS officers (
    code VARCHAR NOT NULL,
    fiscal_period VARCHAR NOT NULL,
    name VARCHAR,
    role VARCHAR,                              -- president / director / auditor
    bio TEXT,
    holdings_pct DOUBLE,
    raw_json JSON
);

CREATE TABLE IF NOT EXISTS ir_documents (
    id VARCHAR PRIMARY KEY,
    code VARCHAR NOT NULL,
    doc_type VARCHAR,                          -- earnings_pres / business_plan / etc
    published_at DATE,
    source_url VARCHAR,
    body_text TEXT,
    extraction_status VARCHAR,                 -- ok / pdf_failed / not_found
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_decisions (
    id VARCHAR PRIMARY KEY,
    code VARCHAR,
    as_of_date DATE,
    role VARCHAR,                              -- bull / bear / judge / postmortem
    model VARCHAR,                             -- claude_code / codex
    prompt TEXT,
    output TEXT,
    confidence DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS falsifiability_scenarios (
    id VARCHAR PRIMARY KEY,
    code VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    narrative TEXT,
    quantitative_triggers JSON,                -- list of {metric, operator, threshold, window}
    qualitative_triggers JSON,                 -- list of {description, hints}
    status VARCHAR DEFAULT 'active',           -- active / triggered / resolved
    triggered_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id VARCHAR PRIMARY KEY,
    code VARCHAR NOT NULL,
    qty INTEGER NOT NULL,
    entry_price DOUBLE NOT NULL,
    entry_date DATE NOT NULL,
    target_price DOUBLE,
    stop_price DOUBLE,
    scenario_id VARCHAR,                       -- 反証シナリオID
    status VARCHAR DEFAULT 'open',             -- open / closed
    exit_price DOUBLE,
    exit_date DATE,
    realized_pnl DOUBLE,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_positions_code_status ON positions(code, status);

CREATE TABLE IF NOT EXISTS postmortems (
    id VARCHAR PRIMARY KEY,
    position_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    closed_at TIMESTAMP,
    summary TEXT,
    what_worked TEXT,
    what_missed TEXT,
    improvement TEXT,
    pattern_tags VARCHAR,                      -- comma separated tags
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS macro_regime_daily (
    date DATE PRIMARY KEY,
    regime VARCHAR,                            -- risk_on / risk_off / neutral
    score DOUBLE,
    components JSON
);

CREATE TABLE IF NOT EXISTS universe_snapshots (
    date DATE NOT NULL,
    code VARCHAR NOT NULL,
    market_cap_jpy BIGINT,
    last_close DOUBLE,
    included BOOLEAN,
    reason VARCHAR,
    PRIMARY KEY (date, code)
);

CREATE TABLE IF NOT EXISTS screening_daily (
    date DATE NOT NULL,
    code VARCHAR NOT NULL,
    score DOUBLE,
    rules_hit JSON,
    rank INTEGER,
    PRIMARY KEY (date, code)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id VARCHAR PRIMARY KEY,
    run_date DATE,
    step VARCHAR,                              -- regime / universe / screening / debate / ...
    status VARCHAR,                            -- success / skipped / failed
    detail TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id VARCHAR PRIMARY KEY,
    code VARCHAR,
    scenario_id VARCHAR,
    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trigger_kind VARCHAR,                      -- quantitative / qualitative
    detail TEXT
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id VARCHAR PRIMARY KEY,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    config JSON,
    start_date DATE,
    end_date DATE,
    sharpe DOUBLE,
    max_drawdown DOUBLE,
    win_rate DOUBLE,
    profit_factor DOUBLE,
    avg_holding_days DOUBLE,
    equity_curve JSON
);
