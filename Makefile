# ChaosGen Makefile - Development Focus

.PHONY: help install test lint clean format dev-install dev-test docs

# Default target
help:
	@echo "ChaosGen - Development Commands"
	@echo ""
	@echo "Development:"
	@echo "  install     - Install dependencies"
	@echo "  dev-install - Install development dependencies"
	@echo "  test        - Run tests"
	@echo "  dev-test    - Run tests with coverage"
	@echo "  lint        - Run linting"
	@echo "  format      - Format code with black"
	@echo "  clean       - Clean up generated files"
	@echo "  docs        - Generate documentation"

# Install dependencies
install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt
	@echo "✅ Dependencies installed"

# Install development dependencies
dev-install:
	@echo "Installing development dependencies..."
	pip install -r requirements.txt
	pip install -e .
	@echo "✅ Development environment ready"

# Run tests
test:
	@echo "Running tests..."
	python -m pytest tests/ -v
	@echo "✅ Tests completed"

# Run development tests with coverage
dev-test:
	@echo "Running development tests..."
	python -m pytest tests/ -v --cov=tools --cov-report=html
	@echo "✅ Development tests completed"

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

# Documentation
docs:
	@echo "Generating documentation..."
	@echo "README.md already exists"
	@echo "✅ Documentation ready"
