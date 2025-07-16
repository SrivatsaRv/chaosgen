# ChaosGen

A streamlined chaos engineering tool that generates experiments for AWS EKS clusters using AI. Leverages LitmusChaos for reliable chaos experiment execution.

## Quick Setup

### Prerequisites

```bash
# Required
- Python 3.11+
- AWS CLI configured with appropriate permissions
- OpenAI API key or Google (Gemini) API key
- AWS EKS cluster with LitmusChaos installed
```


This creates:
- VPC with public/private subnets
- EKS cluster (1.28)
- Self-managed node group

### Installation

1. Clone and setup:
```bash
git clone https://github.com/SrivatsaRv/chaosgen.git
cd chaosgen
python -m venv chaosgen-venv
source chaosgen-venv/bin/activate  # On Windows: .\chaosgen-venv\Scripts\activate
pip install -r requirements.txt
```

### Infrastructure

For testing, use the provided Terraform configuration:

```bash
cd terraform
terraform init
terraform apply
```

2. Configure environment using the setup script:
```bash
python3 setup-env.py
```
This interactive script will help you configure:
- LLM Provider (OpenAI/Gemini)
- API Keys
- Model selection
- Mock mode for testing

3. Configure kubectl for your EKS cluster:
```bash
# List and configure available clusters
python3 craterctl.py configure

# Or specify region and cluster
python3 craterctl.py configure -r us-east-2 -c your-cluster
```

4. Verify setup:
```bash
# Check kubectl configuration
python3 craterctl.py check

# Check LLM configuration
python3 craterctl.py check-llm
```

5. **inventory** (or **ls**) - Show cluster infrastructure
```bash
python3 craterctl.py inventory
python3 craterctl.py ls  # Short alias
```
6. **suggest** - Generate chaos experiments
```bash
# Options:
-n, --count INTEGER      Number of experiments to generate (default: 3)
-o, --output DIRECTORY   Output directory (default: experiments/)
--dry-run               Generate without saving

# Examples:
python3 craterctl.py suggest              # Generate 3 experiments
python3 craterctl.py suggest -n 5         # Generate 5 experiments
python3 craterctl.py suggest --dry-run    # Preview without saving
```


### AI Component Details

1. **Infrastructure Discovery**
   - Tool: `InventoryFetchTool`
   - Purpose: Discovers Kubernetes resources and builds service topology
   - Output: JSON topology with services, relationships, and metadata

2. **AI Experiment Design**
   - Tool: `ExperimentDesigner`
   - Input: Service topology from discovery phase
   - Process:
     ```python
     {
       "services": [
         {"name": "frontend", "type": "deployment", "critical": true, ...},
         {"name": "backend", "type": "statefulset", ...}
       ],
       "relationships": [...],
       "metadata": {...}
     }
     ```
   - LLM Prompt: Uses templates from `prompts/experiment.j2`
   - Output: List of experiment specifications

3. **LLM Integration**
   - Tool: `LLMAdapter`
   - Supported Providers:
     - OpenAI (gpt-3.5-turbo, gpt-4)
     - Google Gemini (gemini-1.5-flash)
   - Configuration: Environment variables or .env file
   - Fallback: Mock mode for testing

4. **Generated Experiments**
   ```json
   {
     "title": "Frontend Pod Failure Test",
     "description": "Test frontend resilience to pod failures",
     "action": "pod-kill",
     "target_selector": {
       "namespace": "default",
       "label_selector": "app=frontend"
     },
     "parameters": {
       "duration": "60s",
       "intensity": 0.5
     },
     "abort_threshold": {
       "metric": "error_rate",
       "value": 0.05
     }
   }
   ```

## ChaosGen CLI (craterctl.py)

### Core Commands

1. **configure** - Set up kubectl for your EKS cluster
```bash
python3 craterctl.py configure [-r REGION] [-c CLUSTER_NAME]
```

2. **check** - Validate kubectl configuration
```bash
python3 craterctl.py check
```

3. **check-llm** - Verify LLM provider setup
```bash
python3 craterctl.py check-llm
```

### Global Options

- `-v, --verbose` - Enable verbose logging



### Development

```bash
# Install development dependencies
make dev-install

# Format code
make format

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

## Validation

ChaosGen relies on LitmusChaos's built-in validation mechanisms:
- CRD validation ensures experiment specifications are correct
- Runtime validation during experiment execution
- Kubernetes native validation for resource specifications

This approach ensures reliable experiment execution while maintaining simplicity.

## License

MIT License
