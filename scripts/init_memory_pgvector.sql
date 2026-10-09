-- Enable pgvector for ORION Memory Gateway (Wave 4).
-- Run against the ORION database (default: orion) before MEMORY_BACKEND=postgres.
CREATE EXTENSION IF NOT EXISTS vector;
