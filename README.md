# ChaosGen

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **AI-Powered Chaos Engineering for Kubernetes Microservices**

ChaosGen is an intelligent chaos engineering tool that automatically generates, executes, and analyzes chaos experiments for Kubernetes microservices applications. It leverages Large Language Models (LLMs) to create context-aware, safe, and high-impact chaos experiments using LitmusChaos.

## Features

- **AI-Powered Experiment Design**: Uses OpenAI GPT or Google Gemini to generate intelligent chaos experiments
- **Infrastructure Discovery**: Automatically discovers Kubernetes services and their dependencies
- **Context-Aware Targeting**: Generates experiments based on actual service topology and criticality
- **Safety First**: Built-in abort thresholds and risk assessment for safe experimentation
- **LitmusChaos Integration**: Generates ready-to-execute LitmusChaos YAML specifications
- **Multi-Provider Support**: Works with OpenAI, Google Gemini, or mock mode for testing
- **Comprehensive Reporting**: Detailed explanations and impact analysis for each experiment
- **Easy Setup**: Interactive configuration and validation tools

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Kubernetes    │    │   ChaosGen CLI   │    │   LLM Provider  │
│   Cluster       │◄──►│   (craterctl.py) │◄──►│  (OpenAI/Gemini)│
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │
         │                       ▼
         │              ┌──────────────────┐
         │              │   Tools Module   │
         │              │                  │
         │              │ • InventoryFetch │
         │              │ • ExperimentDesign│
         │              │ • LLMAdapter     │
         │              └──────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌──────────────────┐
│  LitmusChaos    │    │   Generated      │
│   Experiments   │    │   Experiments    │
└─────────────────┘    └──────────────────┘
```

## Quick Start

### Prerequisites

- **Python 3.11+**
- **kubectl** configured with access to your Kubernetes cluster
- **LitmusChaos** installed in your cluster
- **OpenAI API key** or **Google Gemini API key**

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/one2n/chaosgen.git
cd chaosgen
```

2. **Create virtual environment:**
```bash
python -m venv chaosgen-venv
source chaosgen-venv/bin/activate  # On Windows: .\chaosgen-venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Configure environment:**
```bash
python setup-env.py
```

5. **Verify setup:**
```bash
python craterctl.py check-llm
python craterctl.py check
```

## Usage

### Basic Commands

#### 1. **Discover Infrastructure**
```bash
# Show cluster services and topology
python craterctl.py inventory

# Alternative command
python craterctl.py ls
```

#### 2. **Generate Chaos Experiments**
```bash
# Generate 3 experiments (default)
python craterctl.py suggest

# Generate 5 experiments
python craterctl.py suggest -n 5

# Preview without saving
python craterctl.py suggest --dry-run

# Use custom configuration
python craterctl.py suggest -c my-stack.yaml
```

#### 3. **Manage Kubernetes Contexts**
```bash
# List available contexts
python craterctl.py contexts

# Test context connectivity
python craterctl.py contexts --test

# Switch to specific context
python craterctl.py contexts --switch my-cluster
```

#### 4. **Configure AWS EKS Clusters**
```bash
# Auto-discover and configure EKS clusters
python craterctl.py configure

# Configure specific region
python craterctl.py configure -r us-west-2

# Configure specific cluster
python craterctl.py configure -c my-eks-cluster
```

### Example Output

When you run `python craterctl.py suggest`, ChaosGen generates:

1. **LitmusChaos YAML files** ready for execution
2. **Detailed explanation markdown** with impact analysis
3. **Risk assessment** for each experiment

Example generated experiment:
```yaml
apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: frontend-pod-delete
  namespace: demo
spec:
  appinfo:
    appns: demo
    applabel: "app=frontend"
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
  - name: pod-delete
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: "30"
        - name: CHAOS_INTERVAL
          value: "10"
        - name: FORCE
          value: "false"
```

## Configuration

### Environment Variables

Create a `.env` file or set environment variables:

```bash
# LLM Provider (openai, gemini, or auto)
CHAOSGEN_LLM_PROVIDER=openai

# API Keys
OPENAI_API_KEY=your-openai-key
GOOGLE_API_KEY=your-gemini-key

# Model Configuration
CHAOSGEN_LLM_MODEL=gpt-4

# Mock Mode (for testing)
CHAOSGEN_MOCK_MODE=false

# Kubernetes Configuration
KUBECONFIG=~/.kube/config
LOG_LEVEL=INFO
```

### Stack Configuration

Create a `stack.yaml` file to define your application topology:

```yaml
k8s:
  namespaces:
    - my-app
    - monitoring
  
  target_services:
    - name: frontend
      namespace: my-app
      type: deployment
      critical: true
      labels:
        app: frontend
      dependencies: ["backend", "database"]

experiments:
  default_duration: "60s"
  abort_thresholds:
    error_rate: 0.05
    latency_p95: 2.0
```

## Development

### Setup Development Environment

```bash
# Install development dependencies
make dev-install

# Run tests
make test

# Run linting
make lint

# Format code
make format

# Clean generated files
make clean
```

### Project Structure

```
chaosgen/
├── craterctl.py          # Main CLI application
├── setup-env.py          # Environment setup script
├── stack.yaml            # Default stack configuration
├── requirements.txt      # Python dependencies
├── Makefile             # Development commands
├── tools/               # Core tools
│   ├── inventory_fetch.py    # Kubernetes discovery
│   ├── experiment_designer.py # AI experiment generation
│   └── llm_adapter.py        # LLM integration
├── prompts/             # LLM prompt templates
│   ├── experiment.j2
│   └── litmus-experiment.j2
├── experiments/         # Generated experiments
└── k8s/                # Kubernetes manifests
```

## Troubleshooting

### Common Issues

#### 1. **LLM Connection Issues**
```bash
# Check LLM configuration
python craterctl.py check-llm

# Enable mock mode for testing
export CHAOSGEN_MOCK_MODE=true
```

#### 2. **Kubernetes Connection Issues**
```bash
# Check kubectl configuration
python craterctl.py check

# List available contexts
python craterctl.py contexts

# Test context connectivity
python craterctl.py contexts --test
```

#### 3. **Missing Dependencies**
```bash
# Reinstall dependencies
pip install -r requirements.txt

# Check Python version
python --version  # Should be 3.11+
```

#### 4. **Permission Issues**
```bash
# Ensure kubectl has proper permissions
kubectl auth can-i get pods --all-namespaces

# Check LitmusChaos installation
kubectl get pods -n litmus
```

### Debug Mode

Enable verbose logging:
```bash
python craterctl.py --verbose suggest
```

## Contributing

We welcome contributions! Please see our contributing guidelines:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes** following PEP8 and flake8 standards
4. **Add tests** for new functionality
5. **Run the test suite**: `make test`
6. **Submit a pull request**

### Development Standards

- **Code Style**: Follow PEP8 with black formatting
- **Linting**: Use flake8 for code quality
- **Testing**: Add tests for new features
- **Documentation**: Update docs for API changes
- **Logging**: Use structured logging with structlog

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- **LitmusChaos** for the chaos engineering framework
- **OpenAI** and **Google** for LLM capabilities
- **Kubernetes** community for the orchestration platform

## Support

- **Issues**: [GitHub Issues](https://github.com/one2n/chaosgen/issues)
- **Discussions**: [GitHub Discussions](https://github.com/one2n/chaosgen/discussions)
- **Documentation**: [Wiki](https://github.com/one2n/chaosgen/wiki)

---

**Made with love for resilient microservices**
