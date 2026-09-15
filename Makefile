.PHONY: install test backend aiml-train verify migrate
install:
	cd backend && pip3 install -r requirements.txt
	cd aiml    && pip3 install -r requirements.txt
test:
	cd backend && python3 -m pytest tests/ -q
	cd aiml    && python3 -m tests.smoke_test
	node scripts/tests/parsers.test.mjs
backend:
	cd backend && uvicorn main:app --reload --port 8000
aiml-train:
	cd aiml && python3 -m src.train --source synthetic --n 6000
verify:
	deno run --allow-net --allow-env scripts/verify-live.ts $(ADDR) --hops 2
migrate:
	@ls supabase/migrations/*.sql
