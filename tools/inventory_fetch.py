"""
Kubernetes Inventory Fetch Tool

Discovers services, deployments, statefulsets, and other resources
across configured namespaces and creates a unified service graph.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = structlog.get_logger()


class InventoryFetchTool:
    """
    Fetches Kubernetes inventory and creates a unified service graph.
    
    Discovers:
    - Deployments, StatefulSets, DaemonSets
    - Services and their endpoints
    - ConfigMaps and Secrets
    - Resource limits and requests
    - Labels and annotations
    """
    
    def __init__(self):
        self.v1_apps = None
        self.v1_core = None
        self.v1_networking = None
        self._init_kubernetes_client()
    
    def _init_kubernetes_client(self):
        """Initialize Kubernetes API clients"""
        try:
            # Load kubeconfig
            config.load_kube_config()
            
            # Create API clients
            self.v1_apps = client.AppsV1Api()
            self.v1_core = client.CoreV1Api()
            self.v1_networking = client.NetworkingV1Api()
            
            logger.info("Kubernetes client initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize Kubernetes client", error=str(e))
            raise
    
    def run(self, stack_file: Path) -> Dict[str, Any]:
        """
        Main method to fetch inventory from Kubernetes cluster.
        
        Args:
            stack_file: Path to stack.yaml configuration file
            
        Returns:
            Dictionary containing unified service graph
        """
        logger.info("Starting Kubernetes inventory fetch", stack_file=str(stack_file))
        
        # Load configuration
        config_data = self._load_config(stack_file)
        k8s_config = config_data.get('k8s', {})
        
        # Get namespaces to scan
        namespaces = k8s_config.get('namespaces', ['default'])
        target_services = k8s_config.get('target_services', [])
        
        # Fetch cluster information
        cluster_info = self._get_cluster_info()
        
        # Fetch services from each namespace
        services = []
        for namespace in namespaces:
            try:
                namespace_services = self._fetch_namespace_services(namespace, target_services)
                services.extend(namespace_services)
                logger.info("Fetched services from namespace", namespace=namespace, count=len(namespace_services))
            except Exception as e:
                logger.warning("Failed to fetch from namespace", namespace=namespace, error=str(e))
        
        # Create unified topology
        topology = {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "cluster": cluster_info,
                "namespaces_scanned": namespaces,
                "total_services": len(services)
            },
            "services": services,
            "relationships": self._build_service_relationships(services)
        }
        
        logger.info("Inventory fetch completed", 
                   total_services=len(services),
                   namespaces=len(namespaces))
        
        return topology
    
    def _load_config(self, stack_file: Path) -> Dict[str, Any]:
        """Load and parse stack configuration file"""
        try:
            with open(stack_file, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error("Failed to load stack configuration", error=str(e))
            raise
    
    def _get_cluster_info(self) -> Dict[str, Any]:
        """Get basic cluster information"""
        try:
            # Get cluster version
            version_api = client.VersionApi()
            version_info = version_api.get_code()
            
            # Get nodes info
            nodes = self.v1_core.list_node()
            
            return {
                "kubernetes_version": version_info.git_version,
                "platform": version_info.platform,
                "node_count": len(nodes.items),
                "provider": self._detect_provider(nodes.items)
            }
        except Exception as e:
            logger.warning("Failed to get cluster info", error=str(e))
            return {"error": str(e)}
    
    def _detect_provider(self, nodes: List) -> str:
        """Detect cloud provider from node labels"""
        for node in nodes:
            labels = node.metadata.labels or {}
            if 'eks.amazonaws.com' in str(labels):
                return 'aws-eks'
            elif 'gke.io' in str(labels):
                return 'gcp-gke'
            elif 'aks.azure.com' in str(labels):
                return 'azure-aks'
        return 'unknown'
    
    def _fetch_namespace_services(self, namespace: str, target_services: List[Dict]) -> List[Dict]:
        """Fetch all services from a specific namespace"""
        services = []
        
        # Fetch Deployments
        try:
            deployments = self.v1_apps.list_namespaced_deployment(namespace=namespace)
            for deployment in deployments.items:
                service_info = self._extract_deployment_info(deployment, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            logger.warning("Failed to fetch deployments", namespace=namespace, error=str(e))
        
        # Fetch StatefulSets
        try:
            statefulsets = self.v1_apps.list_namespaced_stateful_set(namespace=namespace)
            for statefulset in statefulsets.items:
                service_info = self._extract_statefulset_info(statefulset, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            logger.warning("Failed to fetch statefulsets", namespace=namespace, error=str(e))
        
        # Fetch DaemonSets
        try:
            daemonsets = self.v1_apps.list_namespaced_daemon_set(namespace=namespace)
            for daemonset in daemonsets.items:
                service_info = self._extract_daemonset_info(daemonset, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            logger.warning("Failed to fetch daemonsets", namespace=namespace, error=str(e))
        
        # Fetch Services
        try:
            k8s_services = self.v1_core.list_namespaced_service(namespace=namespace)
            for k8s_service in k8s_services.items:
                service_info = self._extract_service_info(k8s_service, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            logger.warning("Failed to fetch services", namespace=namespace, error=str(e))
        
        return services
    
    def _extract_deployment_info(self, deployment, namespace: str) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a Deployment"""
        try:
            metadata = deployment.metadata
            spec = deployment.spec
            status = deployment.status
            
            # Get resource requirements
            resources = self._extract_resource_requirements(spec.template.spec.containers)
            
            # Get labels and annotations
            labels = metadata.labels or {}
            annotations = metadata.annotations or {}
            
            return {
                "id": f"{namespace}/{metadata.name}",
                "name": metadata.name,
                "namespace": namespace,
                "env": "k8s",
                "type": "deployment",
                "api_version": deployment.api_version,
                "replicas": {
                    "desired": spec.replicas,
                    "available": status.available_replicas if status.available_replicas else 0,
                    "ready": status.ready_replicas if status.ready_replicas else 0
                },
                "labels": dict(labels),
                "annotations": dict(annotations),
                "resources": resources,
                "containers": [
                    {
                        "name": container.name,
                        "image": container.image,
                        "ports": [{"container_port": port.container_port, "protocol": port.protocol} 
                                for port in container.ports] if container.ports else []
                    }
                    for container in spec.template.spec.containers
                ],
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": metadata.creation_timestamp.isoformat() if metadata.creation_timestamp else None
            }
        except Exception as e:
            logger.warning("Failed to extract deployment info", name=deployment.metadata.name, error=str(e))
            return None
    
    def _extract_statefulset_info(self, statefulset, namespace: str) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a StatefulSet"""
        try:
            metadata = statefulset.metadata
            spec = statefulset.spec
            status = statefulset.status
            
            resources = self._extract_resource_requirements(spec.template.spec.containers)
            labels = metadata.labels or {}
            annotations = metadata.annotations or {}
            
            return {
                "id": f"{namespace}/{metadata.name}",
                "name": metadata.name,
                "namespace": namespace,
                "env": "k8s",
                "type": "statefulset",
                "api_version": statefulset.api_version,
                "replicas": {
                    "desired": spec.replicas,
                    "available": status.available_replicas if status.available_replicas else 0,
                    "ready": status.ready_replicas if status.ready_replicas else 0
                },
                "labels": dict(labels),
                "annotations": dict(annotations),
                "resources": resources,
                "containers": [
                    {
                        "name": container.name,
                        "image": container.image,
                        "ports": [{"container_port": port.container_port, "protocol": port.protocol} 
                                for port in container.ports] if container.ports else []
                    }
                    for container in spec.template.spec.containers
                ],
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": metadata.creation_timestamp.isoformat() if metadata.creation_timestamp else None
            }
        except Exception as e:
            logger.warning("Failed to extract statefulset info", name=statefulset.metadata.name, error=str(e))
            return None
    
    def _extract_daemonset_info(self, daemonset, namespace: str) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a DaemonSet"""
        try:
            metadata = daemonset.metadata
            spec = daemonset.spec
            status = daemonset.status
            
            resources = self._extract_resource_requirements(spec.template.spec.containers)
            labels = metadata.labels or {}
            annotations = metadata.annotations or {}
            
            return {
                "id": f"{namespace}/{metadata.name}",
                "name": metadata.name,
                "namespace": namespace,
                "env": "k8s",
                "type": "daemonset",
                "api_version": daemonset.api_version,
                "replicas": {
                    "desired": status.desired_number_scheduled,
                    "available": status.number_available,
                    "ready": status.number_ready
                },
                "labels": dict(labels),
                "annotations": dict(annotations),
                "resources": resources,
                "containers": [
                    {
                        "name": container.name,
                        "image": container.image,
                        "ports": [{"container_port": port.container_port, "protocol": port.protocol} 
                                for port in container.ports] if container.ports else []
                    }
                    for container in spec.template.spec.containers
                ],
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": metadata.creation_timestamp.isoformat() if metadata.creation_timestamp else None
            }
        except Exception as e:
            logger.warning("Failed to extract daemonset info", name=daemonset.metadata.name, error=str(e))
            return None
    
    def _extract_service_info(self, k8s_service, namespace: str) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a Service"""
        try:
            metadata = k8s_service.metadata
            spec = k8s_service.spec
            
            labels = metadata.labels or {}
            annotations = metadata.annotations or {}
            
            return {
                "id": f"{namespace}/{metadata.name}",
                "name": metadata.name,
                "namespace": namespace,
                "env": "k8s",
                "type": "service",
                "api_version": k8s_service.api_version,
                "cluster_ip": spec.cluster_ip,
                "service_type": spec.type,
                "ports": [
                    {
                        "port": port.port,
                        "target_port": port.target_port,
                        "protocol": port.protocol
                    }
                    for port in spec.ports
                ] if spec.ports else [],
                "selector": dict(spec.selector) if spec.selector else {},
                "labels": dict(labels),
                "annotations": dict(annotations),
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": metadata.creation_timestamp.isoformat() if metadata.creation_timestamp else None
            }
        except Exception as e:
            logger.warning("Failed to extract service info", name=k8s_service.metadata.name, error=str(e))
            return None
    
    def _extract_resource_requirements(self, containers: List) -> Dict[str, Any]:
        """Extract resource requirements from containers"""
        total_requests = {"cpu": "0", "memory": "0"}
        total_limits = {"cpu": "0", "memory": "0"}
        
        for container in containers:
            if container.resources:
                # Sum up requests
                if container.resources.requests:
                    for resource, value in container.resources.requests.items():
                        if resource in total_requests:
                            # Simple addition (in real implementation, you'd want proper resource arithmetic)
                            total_requests[resource] = str(float(total_requests[resource]) + float(value))
                
                # Sum up limits
                if container.resources.limits:
                    for resource, value in container.resources.limits.items():
                        if resource in total_limits:
                            total_limits[resource] = str(float(total_limits[resource]) + float(value))
        
        return {
            "requests": total_requests,
            "limits": total_limits
        }
    
    def _is_critical_service(self, name: str, namespace: str) -> bool:
        """Determine if a service is critical based on configuration or labels"""
        # This could be enhanced with more sophisticated logic
        critical_keywords = ['redis', 'mysql', 'postgres', 'database', 'cache', 'frontend', 'api']
        return any(keyword in name.lower() for keyword in critical_keywords)
    
    def _build_service_relationships(self, services: List[Dict]) -> List[Dict]:
        """Build relationships between services based on selectors and dependencies"""
        relationships = []
        
        # Find service-to-service relationships
        for service in services:
            if service['type'] == 'service' and service.get('selector'):
                selector = service['selector']
                
                # Find deployments/statefulsets that match this selector
                for target in services:
                    if target['type'] in ['deployment', 'statefulset', 'daemonset']:
                        if target['namespace'] == service['namespace']:
                            # Check if labels match selector
                            if self._labels_match_selector(target.get('labels', {}), selector):
                                relationships.append({
                                    "from": service['id'],
                                    "to": target['id'],
                                    "type": "selector_match",
                                    "namespace": service['namespace']
                                })
        
        return relationships
    
    def _labels_match_selector(self, labels: Dict[str, str], selector: Dict[str, str]) -> bool:
        """Check if labels match a selector"""
        for key, value in selector.items():
            if key not in labels or labels[key] != value:
                return False
        return True
    
    def save_topology(self, topology: Dict[str, Any], output_path: Path = Path("context/topo.json")):
        """Save topology to JSON file"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(topology, f, indent=2, default=str)
        
        logger.info("Topology saved", path=str(output_path))
        return output_path 