"""
Experiment Designer Tool

Uses LLM to generate chaos experiments based on Kubernetes topology
and configuration. Generates experiments in a common schema that can
be executed by different chaos engines.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
import structlog

from jinja2 import Template
from openai import OpenAI
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class ExperimentSpec(BaseModel):
    """Pydantic model for experiment specifications"""
    title: str = Field(..., description="Short descriptive name")
    description: str = Field(..., description="Why this experiment matters")
    env: str = Field(default="k8s", description="Environment type")
    action: str = Field(..., description="Chaos action type")
    target_selector: Dict[str, str] = Field(..., description="Target selection criteria")
    parameters: Dict[str, Any] = Field(..., description="Chaos-specific parameters")
    abort_threshold: Dict[str, Any] = Field(..., description="Abort conditions")
    expected_impact: str = Field(..., description="Expected outcome")
    risk_level: str = Field(..., description="Risk assessment")
    chaos_engine: str = Field(..., description="Chaos engine to use")


class ExperimentDesigner:
    """
    Uses LLM to design chaos experiments based on infrastructure topology.
    
    Generates experiments that are:
    - Context-aware (based on actual services)
    - Safe (with proper abort thresholds)
    - High-impact (targeting critical failure modes)
    - Kubernetes-specific
    """
    
    def __init__(self, model: str = "gpt-4o", temperature: float = 0.3):
        self.client = OpenAI()
        self.model = model
        self.temperature = temperature
        self.template = self._load_template()
        
        logger.info("Experiment designer initialized", model=model, temperature=temperature)
    
    def _load_template(self) -> Template:
        """Load the Jinja2 template for experiment generation"""
        template_path = Path(__file__).parent.parent / "prompts" / "experiment.j2"
        
        try:
            with open(template_path, 'r') as f:
                return Template(f.read())
        except Exception as e:
            logger.error("Failed to load experiment template", error=str(e))
            raise
    
    def design(self, topology: Dict[str, Any], count: int = 3, 
               config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Design chaos experiments based on topology.
        
        Args:
            topology: Service topology from inventory fetch
            count: Number of experiments to generate
            config: Optional configuration overrides
            
        Returns:
            List of experiment specifications
        """
        logger.info("Starting experiment design", count=count)
        
        try:
            # Prepare context for LLM
            context = self._prepare_context(topology, count, config)
            
            # Generate prompt
            prompt = self.template.render(**context)
            
            # Call LLM
            response = self._call_llm(prompt)
            
            # Parse and validate experiments
            experiments = self._parse_experiments(response)
            
            # Validate and enhance experiments
            validated_experiments = []
            for exp in experiments[:count]:
                try:
                    validated_exp = ExperimentSpec(**exp)
                    enhanced_exp = self._enhance_experiment(validated_exp.dict(), topology)
                    validated_experiments.append(enhanced_exp)
                except Exception as e:
                    logger.warning("Failed to validate experiment", experiment=exp.get('title'), error=str(e))
            
            logger.info("Experiment design completed", 
                       requested=count, 
                       generated=len(validated_experiments))
            
            return validated_experiments
            
        except Exception as e:
            logger.error("Failed to design experiments", error=str(e))
            raise
    
    def _prepare_context(self, topology: Dict[str, Any], count: int, 
                        config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Prepare context for the LLM prompt"""
        
        # Extract services by type
        services = topology.get('services', [])
        deployments = [s for s in services if s['type'] == 'deployment']
        statefulsets = [s for s in services if s['type'] == 'statefulset']
        k8s_services = [s for s in services if s['type'] == 'service']
        
        # Get critical services
        critical_services = [s for s in services if s.get('critical', False)]
        
        # Get cluster info
        cluster_info = topology.get('metadata', {}).get('cluster', {})
        
        # Get target services from config
        target_services = []
        if config and 'k8s' in config:
            target_services = config['k8s'].get('target_services', [])
        
        return {
            "topo": topology,
            "N": count,
            "deployments": deployments,
            "statefulsets": statefulsets,
            "services": k8s_services,
            "critical_services": critical_services,
            "target_services": target_services,
            "cluster_info": cluster_info,
            "relationships": topology.get('relationships', [])
        }
    
    def _call_llm(self, prompt: str) -> str:
        """Call the LLM with the experiment generation prompt"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert chaos engineering advisor. Generate only valid JSON arrays of experiment specifications."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=self.temperature,
                max_tokens=2000
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error("Failed to call LLM", error=str(e))
            raise
    
    def _parse_experiments(self, response: str) -> List[Dict[str, Any]]:
        """Parse LLM response into experiment specifications"""
        try:
            # Clean up response - extract JSON array
            response = response.strip()
            
            # Remove markdown code blocks if present
            if response.startswith('```json'):
                response = response[7:]
            if response.endswith('```'):
                response = response[:-3]
            
            response = response.strip()
            
            # Parse JSON
            experiments = json.loads(response)
            
            if not isinstance(experiments, list):
                raise ValueError("Expected JSON array of experiments")
            
            logger.info("Parsed experiments from LLM", count=len(experiments))
            return experiments
            
        except Exception as e:
            logger.error("Failed to parse experiments", response=response[:200], error=str(e))
            raise
    
    def _enhance_experiment(self, experiment: Dict[str, Any], 
                          topology: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance experiment with additional metadata and validation"""
        
        # Add metadata
        experiment['metadata'] = {
            'generated_at': topology.get('metadata', {}).get('generated_at'),
            'cluster_info': topology.get('metadata', {}).get('cluster', {}),
            'designer_version': '1.0.0'
        }
        
        # Validate target exists
        target_selector = experiment.get('target_selector', {})
        namespace = target_selector.get('namespace')
        label_selector = target_selector.get('label_selector')
        
        if namespace and label_selector:
            # Check if target exists in topology
            services = topology.get('services', [])
            matching_services = [
                s for s in services 
                if s['namespace'] == namespace and self._labels_match_selector(s.get('labels', {}), label_selector)
            ]
            
            if matching_services:
                experiment['target_validation'] = {
                    'status': 'valid',
                    'matching_services': [s['id'] for s in matching_services]
                }
            else:
                experiment['target_validation'] = {
                    'status': 'warning',
                    'message': 'No services match the target selector'
                }
        
        # Add default values if missing
        if 'parameters' not in experiment:
            experiment['parameters'] = {}
        
        if 'duration' not in experiment['parameters']:
            experiment['parameters']['duration'] = '60s'
        
        if 'intensity' not in experiment['parameters']:
            experiment['parameters']['intensity'] = 0.5
        
        # Ensure abort threshold is set
        if 'abort_threshold' not in experiment:
            experiment['abort_threshold'] = {
                'metric': 'error_rate',
                'value': 0.05,
                'operator': '>'
            }
        
        return experiment
    
    def _labels_match_selector(self, labels: Dict[str, str], selector: str) -> bool:
        """Check if labels match a Kubernetes label selector"""
        # Simple implementation - in production, you'd want proper K8s label selector parsing
        try:
            # Parse selector like "app=redis,component=primary"
            selector_parts = selector.split(',')
            for part in selector_parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    if key not in labels or labels[key] != value:
                        return False
            return True
        except Exception:
            return False
    
    def rank_experiments(self, experiments: List[Dict[str, Any]], 
                        criteria: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Rank experiments by impact and safety.
        
        Args:
            experiments: List of experiment specifications
            criteria: Optional ranking criteria
            
        Returns:
            Ranked list of experiments
        """
        if not criteria:
            criteria = {
                'risk_weight': 0.3,
                'impact_weight': 0.4,
                'complexity_weight': 0.3
            }
        
        def calculate_score(exp: Dict[str, Any]) -> float:
            score = 0.0
            
            # Risk score (lower is better)
            risk_level = exp.get('risk_level', 'medium')
            risk_scores = {'low': 0.8, 'medium': 0.5, 'high': 0.2}
            score += criteria['risk_weight'] * risk_scores.get(risk_level, 0.5)
            
            # Impact score (higher is better for critical services)
            if exp.get('target_validation', {}).get('status') == 'valid':
                score += criteria['impact_weight'] * 0.8
            else:
                score += criteria['impact_weight'] * 0.3
            
            # Complexity score (medium complexity is often best)
            action = exp.get('action', '')
            complexity_scores = {
                'pod-kill': 0.7,
                'network-delay': 0.6,
                'pod-cpu-hog': 0.5,
                'node-drain': 0.3
            }
            score += criteria['complexity_weight'] * complexity_scores.get(action, 0.5)
            
            return score
        
        # Sort by score (descending)
        ranked = sorted(experiments, key=calculate_score, reverse=True)
        
        # Add ranking metadata
        for i, exp in enumerate(ranked):
            exp['ranking'] = {
                'position': i + 1,
                'score': calculate_score(exp)
            }
        
        logger.info("Experiments ranked", count=len(ranked))
        return ranked
    
    def save_experiments(self, experiments: List[Dict[str, Any]], 
                        output_dir: Path = Path("experiments")) -> List[Path]:
        """Save experiments to JSON files"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        saved_files = []
        for i, experiment in enumerate(experiments):
            filename = f"{experiment['title'].lower().replace(' ', '_').replace('-', '_')}.json"
            filepath = output_dir / filename
            
            with open(filepath, 'w') as f:
                json.dump(experiment, f, indent=2, default=str)
            
            saved_files.append(filepath)
            logger.info("Saved experiment", file=str(filepath), title=experiment['title'])
        
        return saved_files 