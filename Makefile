.PHONY: up fixture status stop refresh snapshot check test k8s
up:
	python3 scripts/local.py up
fixture:
	python3 scripts/local.py fixture
status:
	python3 scripts/local.py status
stop:
	python3 scripts/local.py stop
refresh:
	python3 scripts/local.py refresh
snapshot:
	python3 scripts/local.py snapshot
check:
	python3 scripts/local.py check
test:
	python -m pytest -q
k8s:
	python3 scripts/kubernetes.py up
