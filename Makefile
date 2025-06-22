# Chaos Advisor Agent Makefile

.PHONY: help install test lint clean demo setup-demo run-demo

# Default target
help:
	@echo "Chaos Advisor Agent - Available commands:"
	@echo ""
	@echo "Development:"
	@echo "  install     - Install dependencies"
	@echo "  test        - Run tests"
	@echo "  lint        - Run linting"
	@echo "  clean       - Clean up generated files"
	@echo ""
	@echo "Demo:"
	@echo "  setup-demo  - Set up demo environment"
	@echo "  run-demo    - Run demo chaos experiment"
	@echo ""
	@echo "CLI:"
	@echo "  suggest     - Generate experiment suggestions"
	@echo "  inventory   - Show infrastructure inventory"
	@echo "  status      - Check experiment status"

# Install dependencies
install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt
	@echo "✅ Dependencies installed"

# Run tests
test:
	@echo "Running tests..."
	python -m pytest tests/ -v
	@echo "✅ Tests completed"

# Run linting
lint:
	@echo "Running linting..."
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
	flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
	black --check .
	@echo "✅ Linting completed"

# Format code
format:
	@echo "Formatting code..."
	black .
	@echo "✅ Code formatted"

# Clean up generated files
clean:
	@echo "Cleaning up..."
	rm -rf experiments/
	rm -rf reports/
	rm -rf artifacts/
	rm -rf context/
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	find . -name "*.pyc" -delete
	@echo "✅ Cleanup completed"

# Set up demo environment
setup-demo:
	@echo "Setting up demo environment..."
	@echo "This would typically:"
	@echo "1. Create a Kubernetes cluster"
	@echo "2. Install LitmusChaos"
	@echo "3. Deploy sample application (sock-shop)"
	@echo "4. Set up monitoring (Prometheus/Grafana)"
	@echo ""
	@echo "For now, ensure you have:"
	@echo "- kubectl configured"
	@echo "- LitmusChaos installed"
	@echo "- Sample application deployed"
	@echo "- OPENAI_API_KEY set"
	@echo "✅ Demo setup instructions displayed"

# Run demo chaos experiment
run-demo:
	@echo "Running demo chaos experiment..."
	@echo "1. Fetching infrastructure inventory..."
	python craterctl.py inventory
	@echo ""
	@echo "2. Generating experiment suggestions..."
	python craterctl.py suggest --count 3
	@echo ""
	@echo "3. Running a sample experiment..."
	@echo "   (This would execute a chaos experiment)"
	@echo "✅ Demo completed"

# CLI convenience targets
suggest:
	@echo "Generating chaos experiment suggestions..."
	python craterctl.py suggest

inventory:
	@echo "Fetching infrastructure inventory..."
	python craterctl.py inventory

status:
	@echo "Checking experiment status..."
	@echo "Usage: make status RUN_ID=<run-id>"
	@if [ -n "$(RUN_ID)" ]; then \
		python craterctl.py status $(RUN_ID); \
	else \
		echo "Please provide RUN_ID parameter"; \
	fi

# Development helpers
dev-install:
	@echo "Installing development dependencies..."
	pip install -r requirements.txt
	pip install -e .
	@echo "✅ Development environment ready"

dev-test:
	@echo "Running development tests..."
	python -m pytest tests/ -v --cov=tools --cov-report=html
	@echo "✅ Development tests completed"

# Docker helpers
docker-build:
	@echo "Building Docker image..."
	docker build -t chaos-advisor-agent .
	@echo "✅ Docker image built"

docker-run:
	@echo "Running in Docker..."
	docker run --rm -it \
		-e OPENAI_API_KEY=$(OPENAI_API_KEY) \
		-e SLACK_BOT_TOKEN=$(SLACK_BOT_TOKEN) \
		-v $(PWD):/app \
		-w /app \
		chaos-advisor-agent python craterctl.py suggest

# Kubernetes helpers
k8s-install-litmus:
	@echo "Installing LitmusChaos..."
	kubectl apply -f https://litmuschaos.github.io/litmus/2.14.0/rbac.yaml
	kubectl apply -f https://litmuschaos.github.io/litmus/2.14.0/crds.yaml
	kubectl apply -f https://litmuschaos.github.io/litmus/2.14.0/namespaced-scope/litmus-namespaced-scope.yaml
	@echo "✅ LitmusChaos installed"

k8s-deploy-sock-shop:
	@echo "Deploying sock-shop application..."
	kubectl create namespace sock-shop
	kubectl apply -f https://raw.githubusercontent.com/microservices-demo/microservices-demo/master/deploy/kubernetes/complete-demo.yaml -n sock-shop
	@echo "✅ Sock-shop deployed"

# Documentation
docs:
	@echo "Generating documentation..."
	@echo "README.md already exists"
	@echo "✅ Documentation ready"

# Release helpers
release-check:
	@echo "Running release checks..."
	make test
	make lint
	make clean
	@echo "✅ Release checks completed"

# Quick start
quick-start:
	@echo "🚀 Quick Start Guide:"
	@echo ""
	@echo "1. Set up environment variables:"
	@echo "   export OPENAI_API_KEY='your-api-key'"
	@echo "   export SLACK_BOT_TOKEN='your-slack-token' (optional)"
	@echo ""
	@echo "2. Install dependencies:"
	@echo "   make install"
	@echo ""
	@echo "3. Configure your infrastructure in stack.yaml"
	@echo ""
	@echo "4. Generate experiment suggestions:"
	@echo "   make suggest"
	@echo ""
	@echo "5. Run an experiment:"
	@echo "   python craterctl.py run experiments/<experiment>.json"
	@echo ""
	@echo "✅ Quick start guide displayed" 