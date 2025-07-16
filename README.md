# ChaosGen

A streamlined chaos engineering tool that generates experiments for AWS EKS clusters using AI.

## Quick Setup

### Prerequisites

```bash
# Required
- Python 3.11+
- AWS CLI configured
- OpenAI API key
- AWS EKS cluster
```

### Installation

1. Clone and setup:
```bash
git clone https://github.com/SrivatsaRv/chaosgen.git
cd chaosgen
python -m venv chaosgen-venv
source chaosgen-venv/bin/activate  # On Windows: .\chaosgen-venv\Scripts\activate
make install
```

2. Configure:
```bash
cp env.example .env
# Add your OpenAI API key to .env:
# OPENAI_API_KEY=your-key-here
```

3. Update stack.yaml with your cluster details:
```yaml
k8s:
  kubeconfig: ~/.kube/config
  context: your-context
  namespaces:
    - your-namespace
```

### Usage

1. Generate experiments:
```bash
# Generate default experiments
make suggest

# Or specify count
make suggest COUNT=3
```

2. View cluster inventory:
```bash
make inventory
```

Generated experiments are saved in `experiments/` directory.

### Infrastructure

For testing, use the provided Terraform configuration:

```bash
cd terraform
terraform init
terraform apply
```

This creates:
- VPC with public/private subnets
- EKS cluster (1.28)
- Self-managed node group

### Development

```bash
# Run tests
make test

# Run linting
make lint

# Clean generated files
make clean
```

### Cleanup

```bash
# Remove generated files
make clean

# Destroy test infrastructure (if deployed)
cd terraform
terraform destroy
```

## License

MIT License
