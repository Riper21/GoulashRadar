.PHONY: run test warm docker clean

run:
	py -X utf8 -m uvicorn app.main:app --port 8000 --reload

test:
	py -X utf8 tests/test_validate.py
	py -X utf8 tests/test_merge.py
	py -X utf8 tests/test_names.py
	py -X utf8 tests/test_e2e_cassette.py

warm:
	py -X utf8 scripts/warm_cache.py

docker:
	docker-compose up --build

clean:
	del /q supplier_radar.db
