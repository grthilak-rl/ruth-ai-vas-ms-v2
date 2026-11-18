.PHONY: test test-clean

# Every test suite and lint, one summary line each (see scripts/test-all.sh).
test:
	@scripts/test-all.sh

# Remove the cached backend test-runner image.
test-clean:
	-docker rmi ruth-ai-test-runner:local
