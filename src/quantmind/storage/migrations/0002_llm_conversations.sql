-- Conversation-level metadata for Claude Code/Codex debate transcripts.

ALTER TABLE llm_decisions ADD COLUMN IF NOT EXISTS conversation_id VARCHAR;
ALTER TABLE llm_decisions ADD COLUMN IF NOT EXISTS system_prompt TEXT;
ALTER TABLE llm_decisions ADD COLUMN IF NOT EXISTS duration_sec DOUBLE;
ALTER TABLE llm_decisions ADD COLUMN IF NOT EXISTS error TEXT;

CREATE INDEX IF NOT EXISTS idx_llm_decisions_conversation
ON llm_decisions(as_of_date, code, conversation_id);
