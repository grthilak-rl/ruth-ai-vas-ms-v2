# Test runner for ruth-ai-backend: the deployed backend image plus the test
# dependencies from pyproject.toml [dev]. Built and cached by test-all.sh.
ARG BASE_IMAGE=vas-ruthai-deploy-ruth-ai-backend
FROM ${BASE_IMAGE}
RUN pip install --no-cache-dir -q "pytest>=8.0.0,<9.0.0" "pytest-asyncio>=0.23.0,<1.0.0"
