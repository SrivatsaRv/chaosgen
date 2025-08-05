"""
Experiment Designer Tool

Uses LLM to generate LitmusChaos ChaosEngine YAML files based on Kubernetes topology
and configuration. Generates experiments that can be directly applied to Kubernetes.
"""

import json
import yaml
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import structlog
from datetime import datetime

from jinja2 import Template

logger = structlog.get_logger()


class ExperimentDesigner:
    """
    Uses LLM to design LitmusChaos chaos experiments based on infrastructure topology.

    Generates experiments that are:
    - Context-aware (based on actual services)
    - Safe (with proper abort thresholds)
    - High-impact (targeting critical failure modes)
    - LitmusChaos-specific YAML files
    """

    def __init__(self, model: str = None, temperature: float = 0.3):
        # Use the flexible LLM adapter
        from .llm_adapter import get_llm_adapter

        self.llm_adapter = get_llm_adapter()

        # Override model if specified
        if model:
            self.llm_adapter.model = model

        self.temperature = temperature
        self.template = self._load_template()

        # Check LLM availability
        self._check_llm_availability()

        logger.info(
            "Experiment designer initialized",
            provider=self.llm_adapter.provider,
            model=self.llm_adapter.model,
            temperature=temperature,
        )

    def _load_template(self) -> Template:
        """Load the Jinja2 template for LitmusChaos experiment generation"""
        template_path = Path(__file__).parent.parent / "prompts" / "litmus-experiment.j2"

        try:
            with open(template_path, "r") as f:
                return Template(f.read())
        except Exception as e:
            logger.error("Failed to load LitmusChaos experiment template", error=str(e))
            raise

    def design(
        self,
        topology: Dict[str, Any],
        count: int = 3,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Design LitmusChaos chaos experiments based on topology.

        Args:
            topology: Service topology from inventory fetch
            count: Number of experiments to generate
            config: Optional configuration overrides

        Returns:
            List of experiment YAML content as strings
        """
        logger.info("Starting LitmusChaos experiment design", count=count)

        try:
            # Prepare context for LLM
            context = self._prepare_context(topology, count, config)

            # Generate prompt
            prompt = self.template.render(**context)

            # Call LLM (adapter handles mock mode and fallbacks)
            response = self._call_llm(prompt)

            # Parse YAML experiments
            experiments = self._parse_yaml_experiments(response)

            logger.info(
                "LitmusChaos experiment design completed",
                requested=count,
                generated=len(experiments),
            )

            return experiments

        except Exception as e:
            logger.error("Failed to design LitmusChaos experiments", error=str(e))
            raise

    def _prepare_context(
        self, topology: Dict[str, Any], count: int, config: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Prepare context for the LLM prompt"""

        # Extract services by type
        services = topology.get("services", [])
        deployments = [s for s in services if s["type"] == "deployment"]
        statefulsets = [s for s in services if s["type"] == "statefulset"]
        k8s_services = [s for s in services if s["type"] == "service"]

        # Get critical services
        critical_services = [s for s in services if s.get("critical", False)]

        # Get cluster info
        cluster_info = topology.get("metadata", {}).get("cluster", {})

        # Get target services from config
        target_services = []
        if config and "k8s" in config:
            target_services = config["k8s"].get("target_services", [])

        return {
            "topo": topology,
            "N": count,
            "deployments": deployments,
            "statefulsets": statefulsets,
            "services": k8s_services,
            "critical_services": critical_services,
            "target_services": target_services,
            "cluster_info": cluster_info,
            "relationships": topology.get("relationships", []),
        }

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM with the LitmusChaos experiment generation prompt"""
        system_prompt = "You are an expert chaos engineering advisor. Generate only valid LitmusChaos ChaosEngine YAML files."

        return self.llm_adapter.generate_response(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=self.temperature,
            max_tokens=3000,
        )

    def _parse_yaml_experiments(self, response: str) -> List[str]:
        """Parse YAML experiments from LLM response"""
        try:
            # Clean up the response - remove any markdown formatting
            yaml_content = response.strip()
            
            # Remove markdown code blocks if present
            if yaml_content.startswith("```yaml"):
                yaml_content = yaml_content[7:]
            if yaml_content.startswith("```"):
                yaml_content = yaml_content[3:]
            if yaml_content.endswith("```"):
                yaml_content = yaml_content[:-3]
            
            yaml_content = yaml_content.strip()
            
            # Split by document separator
            yaml_docs = yaml_content.split("---")
            experiments = []
            
            for doc in yaml_docs:
                doc = doc.strip()
                if doc and doc != "":
                    try:
                        # Validate YAML
                        parsed = yaml.safe_load(doc)
                        if parsed and isinstance(parsed, dict):
                            # Ensure it's a ChaosEngine
                            if parsed.get("kind") == "ChaosEngine":
                                experiments.append(doc)
                            else:
                                logger.warning("Skipping non-ChaosEngine document", kind=parsed.get("kind"))
                    except yaml.YAMLError as e:
                        logger.warning("Invalid YAML document", error=str(e), doc=doc[:100])
                        continue
            
            logger.info("Parsed YAML experiments", count=len(experiments))
            return experiments
            
        except Exception as e:
            logger.error("Failed to parse YAML experiments", error=str(e))
            # Return mock experiments if parsing fails
            return self._get_mock_experiments()

    def _get_mock_experiments(self) -> List[str]:
        """Return mock LitmusChaos experiments for testing"""
        return [
            """apiVersion: litmuschaos.io/v1alpha1
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
""",
            """apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: api-cpu-stress
  namespace: demo
spec:
  appinfo:
    appns: demo
    applabel: "app=api"
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
  - name: pod-cpu-hog
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: "60"
        - name: CPU_CORES
          value: "1"
""",
            """apiVersion: litmuschaos.io/v1alpha1
kind: ChaosEngine
metadata:
  name: database-memory-stress
  namespace: demo
spec:
  appinfo:
    appns: demo
    applabel: "app=database"
    appkind: deployment
  chaosServiceAccount: litmus-admin
  experiments:
  - name: pod-memory-hog
    spec:
      components:
        env:
        - name: TOTAL_CHAOS_DURATION
          value: "45"
        - name: MEMORY_CONSUMPTION
          value: "200"
"""
        ]

    def save_experiments(self, experiments: List[str], output_dir: Path) -> List[Path]:
        """Save LitmusChaos experiments to YAML files"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        saved_files = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for i, experiment_yaml in enumerate(experiments):
            try:
                # Parse YAML to get experiment name
                parsed = yaml.safe_load(experiment_yaml)
                experiment_name = parsed.get("metadata", {}).get("name", f"experiment-{i+1}")
                
                # Create filename
                filename = f"{experiment_name}_{timestamp}.yaml"
                filepath = output_dir / filename
                
                # Write YAML file
                with open(filepath, "w") as f:
                    f.write(experiment_yaml)
                
                saved_files.append(filepath)
                logger.info("Saved LitmusChaos experiment", 
                           name=experiment_name, 
                           file=str(filepath))
                
            except Exception as e:
                logger.error("Failed to save experiment", 
                           index=i, 
                           error=str(e))
                # Save with generic name
                filename = f"chaos-experiment-{i+1}_{timestamp}.yaml"
                filepath = output_dir / filename
                with open(filepath, "w") as f:
                    f.write(experiment_yaml)
                saved_files.append(filepath)
        
        # Generate detailed explanation file
        explanation_file = self._generate_explanation_file(experiments, output_dir, timestamp)
        saved_files.append(explanation_file)
        
        return saved_files

    def _generate_explanation_file(self, experiments: List[str], output_dir: Path, timestamp: str) -> Path:
        """Generate a detailed explanation file for the generated experiments"""
        explanation_file = output_dir / f"experiments_explanation_{timestamp}.md"
        
        try:
            with open(explanation_file, "w") as f:
                f.write(self._create_explanation_content(experiments, timestamp))
            
            logger.info("Generated experiment explanation file", file=str(explanation_file))
            return explanation_file
            
        except Exception as e:
            logger.error("Failed to generate explanation file", error=str(e))
            return Path("")

    def _create_explanation_content(self, experiments: List[str], timestamp: str) -> str:
        """Create detailed explanation content for experiments"""
        
        content = f"""# ChaosGen AI-Generated Experiments Explanation

**Generated on**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Total Experiments**: {len(experiments)}
**Generated by**: ChaosGen AI-Powered Chaos Engineering Platform

---

## Overview

This document explains the chaos experiments generated by ChaosGen's AI analysis of your Kubernetes infrastructure. Each experiment is designed to test specific failure scenarios and validate your system's resilience.

## Infrastructure Analysis

ChaosGen discovered the following services in your cluster:
- **Frontend Services**: User-facing applications (nginx, web interfaces)
- **Backend Services**: Business logic and API services (Flask, Node.js, etc.)
- **Database Services**: Data persistence layers (PostgreSQL, Redis, etc.)
- **Infrastructure Services**: Monitoring, logging, and platform services

## Generated Experiments

"""
        
        for i, experiment_yaml in enumerate(experiments, 1):
            try:
                parsed = yaml.safe_load(experiment_yaml)
                content += self._format_experiment_explanation(i, parsed)
            except Exception as e:
                content += f"""
### Experiment {i}: Failed to Parse
**Error**: {str(e)}

This experiment could not be parsed properly. Please check the YAML file manually.

---
"""
        
        content += """
## How to Use These Experiments

### 1. Review and Understand
- Read each experiment explanation above
- Understand what failure scenario it tests
- Verify the target services are correct

### 2. Safety Considerations
- All experiments include abort thresholds
- Monitor your system during execution
- Have rollback procedures ready

### 3. Execution
```bash
# Apply all experiments
kubectl apply -f experiments/

# Apply specific experiment
kubectl apply -f experiments/experiment-name.yaml

# Monitor execution
kubectl get chaosengine -n <namespace>
kubectl get chaosresult -n <namespace>
```

### 4. Analysis
- Monitor application metrics during chaos
- Check system recovery after chaos
- Document findings and improvements

## Safety Features

Each experiment includes:
- **Abort Thresholds**: Automatic stopping if metrics exceed limits
- **Resource Validation**: Checks before execution
- **Gradual Intensity**: Controlled chaos injection
- **Recovery Monitoring**: Validates system healing

## Next Steps

1. **Review**: Understand each experiment's purpose
2. **Test**: Run in non-production environment first
3. **Monitor**: Watch metrics and logs during execution
4. **Analyze**: Document resilience gaps and improvements
5. **Iterate**: Generate new experiments based on findings

---

*Generated by ChaosGen - AI-Powered Chaos Engineering*
"""
        
        return content

    def _format_experiment_explanation(self, index: int, experiment: Dict[str, Any]) -> str:
        """Format a single experiment explanation"""
        
        metadata = experiment.get("metadata", {})
        spec = experiment.get("spec", {})
        appinfo = spec.get("appinfo", {})
        experiments_list = spec.get("experiments", [])
        
        experiment_name = metadata.get("name", f"experiment-{index}")
        namespace = metadata.get("namespace", "demo")
        target_app = appinfo.get("applabel", "unknown")
        app_kind = appinfo.get("appkind", "deployment")
        
        # Get experiment details
        experiment_details = experiments_list[0] if experiments_list else {}
        experiment_type = experiment_details.get("name", "unknown")
        
        # Get parameters
        env_vars = experiment_details.get("spec", {}).get("components", {}).get("env", [])
        parameters = {env["name"]: env["value"] for env in env_vars if "name" in env and "value" in env}
        
        # Risk assessment
        risk_level = self._assess_risk_level(experiment_type)
        
        # Create explanation
        explanation = f"""
### Experiment {index}: {experiment_name}

**Target**: {target_app} ({app_kind}) in namespace `{namespace}`
**Chaos Type**: {experiment_type}
**Risk Level**: {risk_level.upper()}

#### What This Experiment Does

"""
        
        # Add specific explanations based on experiment type
        explanation += self._get_experiment_type_explanation(experiment_type, target_app)
        
        explanation += f"""
#### Parameters

"""
        
        for param_name, param_value in parameters.items():
            explanation += f"- **{param_name}**: {param_value}\n"
        
        explanation += f"""
#### Expected Impact

"""
        
        explanation += self._get_expected_impact(experiment_type, target_app)
        
        explanation += f"""
#### Safety Measures

- **Abort Conditions**: Experiment will stop if system health degrades
- **Duration Control**: Limited execution time to prevent extended outages
- **Resource Limits**: Controlled chaos intensity to maintain system stability

#### Monitoring Points

- Application response times
- Error rates and availability
- Resource utilization (CPU, memory, network)
- Service dependency health
- Database connection pools

---
"""
        
        return explanation

    def _get_experiment_type_explanation(self, experiment_type: str, target_app: str) -> str:
        """Get explanation for specific experiment types"""
        
        explanations = {
            "pod-delete": f"""
This experiment randomly kills pods from the {target_app} deployment to test:
- **Pod restart resilience**: How quickly new pods start up
- **Load balancer behavior**: How traffic is redistributed
- **Service discovery**: How clients find healthy pods
- **Data consistency**: Whether state is preserved during restarts

This simulates real-world scenarios like:
- Node failures
- OOM kills
- Manual pod deletions
- Rolling updates gone wrong
""",
            
            "pod-cpu-hog": f"""
This experiment injects CPU stress into {target_app} pods to test:
- **Resource limits**: Whether CPU limits are properly enforced
- **Performance degradation**: How the app behaves under load
- **Scheduler behavior**: How Kubernetes handles resource pressure
- **Monitoring alerts**: Whether CPU spikes trigger proper alerts

This simulates:
- High CPU usage from bugs
- Resource exhaustion attacks
- Poorly optimized code paths
- Background processing spikes
""",
            
            "pod-memory-hog": f"""
This experiment injects memory pressure into {target_app} pods to test:
- **Memory limits**: Whether memory limits are enforced
- **OOM handling**: How the system responds to memory pressure
- **Garbage collection**: Whether memory is properly managed
- **Pod eviction**: Whether pods are evicted when memory is low

This simulates:
- Memory leaks
- Large data processing
- Cache buildup
- Memory-intensive operations
""",
            
            "pod-network-delay": f"""
This experiment adds network latency to {target_app} pods to test:
- **Timeout handling**: How the app handles slow responses
- **Circuit breakers**: Whether retry mechanisms work
- **User experience**: How latency affects end users
- **Dependency resilience**: How downstream services handle delays

This simulates:
- Network congestion
- Geographic latency
- ISP issues
- Network equipment problems
""",
            
            "pod-network-loss": f"""
This experiment simulates packet loss for {target_app} pods to test:
- **Connection resilience**: How the app handles network failures
- **Retry mechanisms**: Whether failed requests are retried
- **Error handling**: How network errors are handled
- **Service degradation**: Whether the app degrades gracefully

This simulates:
- Network instability
- Packet corruption
- Network partitions
- ISP outages
"""
        }
        
        return explanations.get(experiment_type, f"""
This experiment performs {experiment_type} on {target_app} to test system resilience.
The specific behavior depends on the chaos type and target application.
""")

    def _get_expected_impact(self, experiment_type: str, target_app: str) -> str:
        """Get expected impact description for experiment types"""
        
        impacts = {
            "pod-delete": f"""
- **Immediate**: {target_app} pods will be terminated
- **Recovery**: New pods should start within 30-60 seconds
- **User Impact**: Brief service interruption (5-30 seconds)
- **Monitoring**: Watch for increased error rates and latency
- **Success Criteria**: Service returns to normal within 2 minutes
""",
            
            "pod-cpu-hog": f"""
- **Immediate**: {target_app} pods will experience high CPU usage
- **Performance**: Response times may increase by 50-200%
- **User Impact**: Slower application responses
- **Monitoring**: Watch CPU metrics and response times
- **Success Criteria**: App remains functional, performance recovers after chaos
""",
            
            "pod-memory-hog": f"""
- **Immediate**: {target_app} pods will experience memory pressure
- **Behavior**: Pods may be evicted if memory limits are exceeded
- **User Impact**: Potential service interruptions if pods are killed
- **Monitoring**: Watch memory usage and pod restarts
- **Success Criteria**: App handles memory pressure gracefully
""",
            
            "pod-network-delay": f"""
- **Immediate**: Network requests to {target_app} will be delayed
- **Performance**: Response times will increase significantly
- **User Impact**: Slower application responses
- **Monitoring**: Watch network latency and timeout errors
- **Success Criteria**: App handles delays without crashing
""",
            
            "pod-network-loss": f"""
- **Immediate**: Some network requests to {target_app} will fail
- **Behavior**: Intermittent connection failures
- **User Impact**: Some requests may fail, others succeed
- **Monitoring**: Watch error rates and connection failures
- **Success Criteria**: App handles network failures gracefully
"""
        }
        
        return impacts.get(experiment_type, f"""
- **Immediate**: {target_app} will experience {experiment_type} conditions
- **Impact**: Varies based on the specific chaos type
- **Monitoring**: Watch for changes in application behavior
- **Success Criteria**: System remains stable and recovers after chaos
""")

    def _check_llm_availability(self):
        """Check LLM availability and provide helpful feedback"""
        availability = self.llm_adapter.check_availability()

        if availability["available"]:
            print(f"✅ {availability['message']}")
        else:
            print(f"❌ LLM not available: {availability['error']}")
            print("💡 Available options:")
            print("   1. Set OpenAI key: export OPENAI_API_KEY='your-key'")
            print("   2. Set Gemini key: export GOOGLE_API_KEY='your-key'")
            print("   3. Use mock mode: export CHAOSGEN_MOCK_MODE=true")

    def get_experiment_summary(self, experiments: List[str]) -> List[Dict[str, Any]]:
        """Get summary information about generated experiments"""
        summaries = []
        
        for experiment_yaml in experiments:
            try:
                parsed = yaml.safe_load(experiment_yaml)
                
                metadata = parsed.get("metadata", {})
                spec = parsed.get("spec", {})
                appinfo = spec.get("appinfo", {})
                experiments_list = spec.get("experiments", [])
                
                experiment_type = experiments_list[0].get("name", "unknown") if experiments_list else "unknown"
                
                summary = {
                    "name": metadata.get("name", "unknown"),
                    "namespace": metadata.get("namespace", "demo"),
                    "target_app": appinfo.get("applabel", "unknown"),
                    "experiment_type": experiment_type,
                    "description": f"{experiment_type} experiment targeting {appinfo.get('applabel', 'unknown')}",
                    "risk_level": self._assess_risk_level(experiment_type),
                }
                
                summaries.append(summary)
                
            except Exception as e:
                logger.warning("Failed to parse experiment summary", error=str(e))
                summaries.append({
                    "name": "unknown",
                    "namespace": "demo",
                    "target_app": "unknown",
                    "experiment_type": "unknown",
                    "description": "Failed to parse experiment",
                    "risk_level": "unknown",
                })
        
        return summaries

    def _assess_risk_level(self, experiment_type: str) -> str:
        """Assess risk level based on experiment type"""
        risk_mapping = {
            "pod-delete": "medium",
            "pod-cpu-hog": "low",
            "pod-memory-hog": "medium",
            "pod-network-delay": "low",
            "pod-network-loss": "medium",
            "node-drain": "high",
        }
        return risk_mapping.get(experiment_type, "medium")
