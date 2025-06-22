"""
Executor Adapter Tool

Converts experiment specifications to Kubernetes chaos engine manifests
and executes them. Currently supports LitmusChaos.
"""

import json
import yaml
import uuid
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = structlog.get_logger()


class ExecutorAdapter:
    """
    Converts experiment specs to chaos engine manifests and executes them.
    
    Supports:
    - LitmusChaos (primary)
    - Chaos Mesh (planned)
    """
    
    def __init__(self):
        self.v1_custom = None
        self.v1_core = None
        self._init_kubernetes_client()
        self.active_runs = {}  # Track active experiment runs
    
    def _init_kubernetes_client(self):
        """Initialize Kubernetes API clients"""
        try:
            config.load_kube_config()
            self.v1_custom = client.CustomObjectsApi()
            self.v1_core = client.CoreV1Api()
            logger.info("Kubernetes client initialized for chaos execution")
        except Exception as e:
            logger.error("Failed to initialize Kubernetes client", error=str(e))
            raise
    
    def apply(self, spec: Dict[str, Any], dry_run: bool = False) -> str:
        """
        Apply a chaos experiment specification.
        
        Args:
            spec: Experiment specification
            dry_run: If True, only validate and generate manifests
            
        Returns:
            Run ID for tracking
        """
        logger.info("Applying chaos experiment", title=spec.get('title'), dry_run=dry_run)
        
        try:
            # Validate specification
            self._validate_spec(spec)
            
            # Generate run ID
            run_id = f"chaos-{uuid.uuid4().hex[:8]}"
            
            # Convert to chaos engine manifest
            chaos_engine = self._convert_to_chaos_engine(spec, run_id)
            
            if dry_run:
                logger.info("Dry run completed", run_id=run_id)
                return run_id
            
            # Apply to cluster
            self._apply_chaos_engine(chaos_engine, spec.get('target_selector', {}).get('namespace', 'default'))
            
            # Track the run
            self.active_runs[run_id] = {
                'spec': spec,
                'engine': chaos_engine,
                'started_at': datetime.utcnow().isoformat(),
                'status': 'running'
            }
            
            logger.info("Chaos experiment started", run_id=run_id, title=spec.get('title'))
            return run_id
            
        except Exception as e:
            logger.error("Failed to apply chaos experiment", error=str(e))
            raise
    
    def _validate_spec(self, spec: Dict[str, Any]):
        """Validate experiment specification"""
        required_fields = ['title', 'action', 'target_selector', 'parameters']
        
        for field in required_fields:
            if field not in spec:
                raise ValueError(f"Missing required field: {field}")
        
        # Validate target selector
        target_selector = spec['target_selector']
        if 'namespace' not in target_selector:
            raise ValueError("Target selector must include namespace")
        
        # Validate parameters
        parameters = spec['parameters']
        if 'duration' not in parameters:
            raise ValueError("Parameters must include duration")
    
    def _convert_to_chaos_engine(self, spec: Dict[str, Any], run_id: str) -> Dict[str, Any]:
        """Convert experiment spec to LitmusChaos ChaosEngine manifest"""
        
        action = spec['action']
        target_selector = spec['target_selector']
        parameters = spec['parameters']
        
        # Generate ChaosEngine name
        engine_name = f"{run_id}-{action.replace('-', '-')}"
        
        # Base ChaosEngine template
        chaos_engine = {
            "apiVersion": "litmuschaos.io/v1alpha1",
            "kind": "ChaosEngine",
            "metadata": {
                "name": engine_name,
                "namespace": target_selector['namespace'],
                "labels": {
                    "chaos-run-id": run_id,
                    "chaos-action": action,
                    "app.kubernetes.io/name": "chaos-advisor"
                }
            },
            "spec": {
                "appinfo": {
                    "appns": target_selector['namespace'],
                    "applabel": target_selector.get('label_selector', ''),
                    "appkind": target_selector.get('resource_type', 'deployment')
                },
                "chaosServiceAccount": "litmus-admin",
                "monitoring": True,
                "jobCleanUpPolicy": "retain",
                "annotationCheck": "false"
            }
        }
        
        # Add experiment-specific configuration
        if action == "pod-kill":
            chaos_engine["spec"]["experiments"] = [{
                "name": "pod-delete",
                "spec": {
                    "components": {
                        "env": [
                            {
                                "name": "TOTAL_CHAOS_DURATION",
                                "value": parameters.get('duration', '60')
                            },
                            {
                                "name": "CHAOS_INTERVAL",
                                "value": "10"
                            },
                            {
                                "name": "FORCE",
                                "value": "false"
                            }
                        ]
                    }
                }
            }]
        
        elif action == "pod-cpu-hog":
            chaos_engine["spec"]["experiments"] = [{
                "name": "pod-cpu-hog",
                "spec": {
                    "components": {
                        "env": [
                            {
                                "name": "TOTAL_CHAOS_DURATION",
                                "value": parameters.get('duration', '60')
                            },
                            {
                                "name": "CPU_CORES",
                                "value": str(int(parameters.get('intensity', 0.5) * 2))
                            },
                            {
                                "name": "CHAOS_INTERVAL",
                                "value": "10"
                            }
                        ]
                    }
                }
            }]
        
        elif action == "pod-memory-hog":
            chaos_engine["spec"]["experiments"] = [{
                "name": "pod-memory-hog",
                "spec": {
                    "components": {
                        "env": [
                            {
                                "name": "TOTAL_CHAOS_DURATION",
                                "value": parameters.get('duration', '60')
                            },
                            {
                                "name": "MEMORY_CONSUMPTION",
                                "value": str(int(parameters.get('intensity', 0.5) * 100))
                            },
                            {
                                "name": "CHAOS_INTERVAL",
                                "value": "10"
                            }
                        ]
                    }
                }
            }]
        
        elif action == "network-delay":
            chaos_engine["spec"]["experiments"] = [{
                "name": "pod-network-latency",
                "spec": {
                    "components": {
                        "env": [
                            {
                                "name": "TOTAL_CHAOS_DURATION",
                                "value": parameters.get('duration', '60')
                            },
                            {
                                "name": "NETWORK_LATENCY",
                                "value": str(int(parameters.get('intensity', 0.5) * 200))
                            },
                            {
                                "name": "CHAOS_INTERVAL",
                                "value": "10"
                            }
                        ]
                    }
                }
            }]
        
        elif action == "network-loss":
            chaos_engine["spec"]["experiments"] = [{
                "name": "pod-network-loss",
                "spec": {
                    "components": {
                        "env": [
                            {
                                "name": "TOTAL_CHAOS_DURATION",
                                "value": parameters.get('duration', '60')
                            },
                            {
                                "name": "LOSS_PERCENTAGE",
                                "value": str(int(parameters.get('intensity', 0.5) * 50))
                            },
                            {
                                "name": "CHAOS_INTERVAL",
                                "value": "10"
                            }
                        ]
                    }
                }
            }]
        
        else:
            raise ValueError(f"Unsupported chaos action: {action}")
        
        return chaos_engine
    
    def _apply_chaos_engine(self, chaos_engine: Dict[str, Any], namespace: str):
        """Apply ChaosEngine to Kubernetes cluster"""
        try:
            # Create namespace if it doesn't exist
            self._ensure_namespace(namespace)
            
            # Apply ChaosEngine
            self.v1_custom.create_namespaced_custom_object(
                group="litmuschaos.io",
                version="v1alpha1",
                namespace=namespace,
                plural="chaosengines",
                body=chaos_engine
            )
            
            logger.info("ChaosEngine applied successfully", 
                       name=chaos_engine['metadata']['name'],
                       namespace=namespace)
            
        except ApiException as e:
            logger.error("Failed to apply ChaosEngine", 
                        status=e.status, 
                        reason=e.reason,
                        body=e.body)
            raise
    
    def _ensure_namespace(self, namespace: str):
        """Ensure namespace exists"""
        try:
            self.v1_core.read_namespace(name=namespace)
        except ApiException as e:
            if e.status == 404:
                # Create namespace
                namespace_obj = client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=namespace)
                )
                self.v1_core.create_namespace(body=namespace_obj)
                logger.info("Created namespace", namespace=namespace)
            else:
                raise
    
    def get_status(self, run_id: str) -> Dict[str, Any]:
        """Get status of a chaos experiment run"""
        if run_id not in self.active_runs:
            raise ValueError(f"Run ID not found: {run_id}")
        
        run_info = self.active_runs[run_id]
        spec = run_info['spec']
        engine_name = run_info['engine']['metadata']['name']
        namespace = spec['target_selector']['namespace']
        
        try:
            # Get ChaosEngine status
            engine = self.v1_custom.get_namespaced_custom_object(
                group="litmuschaos.io",
                version="v1alpha1",
                namespace=namespace,
                plural="chaosengines",
                name=engine_name
            )
            
            # Get ChaosResult status
            result_name = f"{engine_name}-{spec['action'].replace('-', '-')}"
            try:
                result = self.v1_custom.get_namespaced_custom_object(
                    group="litmuschaos.io",
                    version="v1alpha1",
                    namespace=namespace,
                    plural="chaosresults",
                    name=result_name
                )
                result_status = result.get('status', {})
            except ApiException:
                result_status = {}
            
            # Determine overall status
            engine_status = engine.get('status', {})
            phase = engine_status.get('engineStatus', 'unknown')
            
            if phase == 'completed':
                status = 'completed'
            elif phase == 'stopped':
                status = 'aborted'
            elif phase == 'running':
                status = 'running'
            else:
                status = 'unknown'
            
            # Update run info
            run_info['status'] = status
            run_info['last_check'] = datetime.utcnow().isoformat()
            
            return {
                'run_id': run_id,
                'status': status,
                'started_at': run_info['started_at'],
                'engine_status': engine_status,
                'result_status': result_status,
                'spec': spec
            }
            
        except ApiException as e:
            if e.status == 404:
                # Engine not found, might have been cleaned up
                run_info['status'] = 'completed'
                return {
                    'run_id': run_id,
                    'status': 'completed',
                    'started_at': run_info['started_at'],
                    'note': 'Engine not found, may have been cleaned up'
                }
            else:
                logger.error("Failed to get run status", run_id=run_id, error=str(e))
                raise
    
    def abort(self, run_id: str):
        """Abort a running chaos experiment"""
        if run_id not in self.active_runs:
            raise ValueError(f"Run ID not found: {run_id}")
        
        run_info = self.active_runs[run_id]
        engine_name = run_info['engine']['metadata']['name']
        namespace = run_info['spec']['target_selector']['namespace']
        
        try:
            # Delete ChaosEngine to abort
            self.v1_custom.delete_namespaced_custom_object(
                group="litmuschaos.io",
                version="v1alpha1",
                namespace=namespace,
                plural="chaosengines",
                name=engine_name
            )
            
            run_info['status'] = 'aborted'
            run_info['aborted_at'] = datetime.utcnow().isoformat()
            
            logger.info("Chaos experiment aborted", run_id=run_id)
            
        except ApiException as e:
            logger.error("Failed to abort experiment", run_id=run_id, error=str(e))
            raise
    
    def list_runs(self) -> List[Dict[str, Any]]:
        """List all tracked runs"""
        return [
            {
                'run_id': run_id,
                'title': info['spec'].get('title'),
                'status': info['status'],
                'started_at': info['started_at']
            }
            for run_id, info in self.active_runs.items()
        ]
    
    def cleanup_completed(self):
        """Clean up completed runs from memory"""
        completed_runs = [
            run_id for run_id, info in self.active_runs.items()
            if info['status'] in ['completed', 'aborted']
        ]
        
        for run_id in completed_runs:
            del self.active_runs[run_id]
        
        if completed_runs:
            logger.info("Cleaned up completed runs", count=len(completed_runs))
    
    def save_manifest(self, chaos_engine: Dict[str, Any], output_path: Path):
        """Save ChaosEngine manifest to file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            yaml.dump(chaos_engine, f, default_flow_style=False, indent=2)
        
        logger.info("ChaosEngine manifest saved", path=str(output_path)) 