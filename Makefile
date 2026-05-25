.PHONY: ci ci-server ci-worker ci-plugin dev-server dev-worker deploy-server install-worker fmt

ci: ci-server ci-worker ci-plugin

ci-server:
	cd server && $(MAKE) ci

ci-worker:
	cd worker && $(MAKE) ci

ci-plugin:
	cd plugin && npm run ci

dev-server:
	cd server && $(MAKE) dev

dev-worker:
	cd worker && $(MAKE) dev

deploy-server:
	./scripts/deploy-server.sh

install-worker:
	./scripts/install-worker.sh

fmt:
	cd server && $(MAKE) fmt
	cd worker && $(MAKE) fmt
	cd plugin && npm run fmt
