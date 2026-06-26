SHELL := bash
ROOT_DIR := $(shell pwd)
DATA_DIR := $(ROOT_DIR)/backend/data/poe2_data
PYTHON := python
GGPK_EXPORT := $(ROOT_DIR)/backend/scripts/ggpk/export_en_tc.py
SC_EXTRACT := $(ROOT_DIR)/backend/scripts/ggpk/extract_sc.py
IMPORT_DATA := $(ROOT_DIR)/backend/scripts/import_game_data.py
VERIFY_DATA := $(ROOT_DIR)/scripts/pipeline/verify_data_completeness.py

.PHONY: help \
	data-ggpk-export \
	data-sc-extract \
	data-tc-fix \
	data-trade-sync \
	verify-critical \
	verify-full \
	data-import \
	clean-verify

help:
	@echo "Data pipeline targets:"
	@echo "  make data-ggpk-export   Export EN+TC from international GGPK"
	@echo "  make data-sc-extract    Extract SC from CN WeGame Bundles2"
	@echo "  make data-tc-fix        Re-export only TC missing tables"
	@echo "  make data-trade-sync    Fetch trade items/stats bilingual data"
	@echo "  make verify-critical    Verify critical TC tables only"
	@echo "  make verify-full        Verify EN/SC/TC completeness"
	@echo "  make data-import        Import poe2_data into Postgres (dry-run by default)"
	@echo "  make clean-verify       Remove verify cache/output if any"

data-ggpk-export:
	@echo "[pipeline] EN+TC GGPK export"
	$(PYTHON) "$(GGPK_EXPORT)" --output "$(DATA_DIR)"
	$(PYTHON) "$(VERIFY_DATA)" --data-dir "$(DATA_DIR)" --critical-only

data-sc-extract:
	@echo "[pipeline] SC extraction"
	$(PYTHON) "$(SC_EXTRACT)" --output "$(DATA_DIR)"
	$(PYTHON) "$(VERIFY_DATA)" --data-dir "$(DATA_DIR)" --critical-only

data-tc-fix:
	@echo "[pipeline] TC fix: export missing TC tables only"
	@set -e; \
	TABLES=$$( $(PYTHON) - <<'PY'
import sys
from pathlib import Path
root=Path('$(DATA_DIR)')
en=sorted(p.name for p in (root/'en').glob('*.json'))
tc=sorted(p.name for p in (root/'tc').glob('*.json'))
miss=sorted(set(en)-set(tc))
print(' '.join(f.replace('.json','') for f in miss))
PY
); \
	if [ -z "$$TABLES" ]; then \
		echo "No TC missing tables detected"; \
	else \
		echo "Re-exporting TC tables: $$TABLES"; \
		$(PYTHON) "$(GGPK_EXPORT)" --output "$(DATA_DIR)" --tables $$TABLES; \
	fi
	$(PYTHON) "$(VERIFY_DATA)" --data-dir "$(DATA_DIR)" --critical-only

data-trade-sync:
	@echo "[pipeline] Trade bilingual sync"
	$(PYTHON) "$(ROOT_DIR)/scripts/fetch_trade_items_bilingual.py"
	$(PYTHON) "$(ROOT_DIR)/scripts/fetch_trade_stats_bilingual.py"

verify-critical:
	@echo "[pipeline] Verify critical tables only"
	$(PYTHON) "$(VERIFY_DATA)" --data-dir "$(DATA_DIR)" --critical-only

verify-full:
	@echo "[pipeline] Verify full EN/SC/TC completeness"
	$(PYTHON) "$(VERIFY_DATA)" --data-dir "$(DATA_DIR)"

data-import:
	@echo "[pipeline] Import game data (dry-run)"
	$(PYTHON) "$(IMPORT_DATA)" --data-dir "$(DATA_DIR)" --dry-run

clean-verify:
	@echo "[pipeline] Clean verify artifacts (none currently)"
	@true
