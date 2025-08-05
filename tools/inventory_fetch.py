"""
Kubernetes Inventory Fetch Tool

Discovers services, deployments, statefulsets, and other resources
through pure Kubernetes API discovery. No configuration files needed.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import os
import re

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = structlog.get_logger()


class InventoryFetchError(Exception):
    """Custom exception for inventory fetch errors"""
    pass


class InventoryFetchTool:
    """
    Fetches Kubernetes inventory through pure API discovery.
    
    Features:
    - Auto-discovers services across namespaces
    - Infers service relationships and dependencies
    - No configuration files required
    - Mock mode for testing
    """

    def __init__(self):
        self.v1_apps = None
        self.v1_core = None
        self.v1_networking = None
        self.mock_mode = os.getenv("CHAOS_MOCK_MODE", "false").lower() == "true"
        self.errors = []
        self.warnings = []
        self.suggestions = []

    def _init_kubernetes_clients(self):
        """Initialize Kubernetes API clients"""
        try:
            # Try to load in-cluster config first, then local kubeconfig
            try:
                config.load_incluster_config()
                logger.info("kubernetes_config_loaded", source="in_cluster")
            except config.ConfigException:
                config.load_kube_config()
                logger.info("kubernetes_config_loaded", source="local_kubeconfig")

            self.v1_core = client.CoreV1Api()
            self.v1_apps = client.AppsV1Api()
            self.v1_networking = client.NetworkingV1Api()
            
            logger.info("kubernetes_clients_initialized", 
                       clients=["CoreV1Api", "AppsV1Api", "NetworkingV1Api"])

        except Exception as e:
            logger.error("kubernetes_client_init_failed", error=str(e))
            raise InventoryFetchError(f"Failed to initialize Kubernetes clients: {str(e)}")

    def _get_cluster_info(self) -> Dict[str, Any]:
        """Get basic cluster information"""
        try:
            version = client.VersionApi().get_code()
            nodes = self.v1_core.list_node()
            
            cluster_info = {
                "kubernetes_version": version.git_version,
                "node_count": len(nodes.items),
                "provider": self._detect_provider(nodes.items),
            }
            
            logger.info("cluster_info_retrieved", 
                       version=cluster_info["kubernetes_version"],
                       node_count=cluster_info["node_count"],
                       provider=cluster_info["provider"])
            
            return cluster_info
            
        except Exception as e:
            logger.warning("cluster_info_fetch_failed", error=str(e))
            return {"kubernetes_version": "unknown", "node_count": 0, "provider": "unknown"}

    def _detect_provider(self, nodes) -> str:
        """Detect cloud provider from node labels"""
        if not nodes:
            return "unknown"
        
        node = nodes[0]
        labels = node.metadata.labels or {}
        
        if "eks.amazonaws.com" in str(labels):
            return "aws-eks"
        elif "gke.io" in str(labels):
            return "gcp-gke"
        elif "kubernetes.azure.com" in str(labels):
            return "azure-aks"
        else:
            return "unknown"

    def _discover_namespaces(self, exclude_system: bool = True) -> List[str]:
        """Discover all namespaces, optionally excluding system ones"""
        try:
            namespaces = self.v1_core.list_namespace()
            namespace_names = [ns.metadata.name for ns in namespaces.items]
            
            if exclude_system:
                # Filter out common system namespaces
                system_namespaces = {
                    'kube-system', 'kube-public', 'kube-node-lease', 
                    'kubernetes-dashboard', 'istio-system', 'linkerd',
                    'monitoring', 'logging', 'cert-manager'
                }
                namespace_names = [ns for ns in namespace_names if ns not in system_namespaces]
            
            logger.info("namespaces_discovered", 
                       total_count=len(namespace_names),
                       namespaces=namespace_names,
                       excluded_system=exclude_system)
            
            return namespace_names
            
        except Exception as e:
            logger.warning("namespace_discovery_failed", error=str(e))
            self.warnings.append(f"Could not discover namespaces: {str(e)}")
            return ["default"]

    def _fetch_deployments(self, namespace: str) -> List[Dict[str, Any]]:
        """Fetch all deployments in a namespace"""
        try:
            deployments = self.v1_apps.list_namespaced_deployment(namespace)
            services = []
            
            for deployment in deployments.items:
                # Get associated service
                service_info = self._find_service_for_deployment(namespace, deployment)
                
                service = {
                    "name": deployment.metadata.name,
                    "namespace": namespace,
                    "type": "deployment",
                    "replicas": deployment.spec.replicas or 1,
                    "labels": deployment.metadata.labels or {},
                    "selector": deployment.spec.selector.match_labels or {},
                    "containers": self._extract_container_info(deployment.spec.template.spec.containers),
                    "service": service_info,
                    "critical": self._infer_criticality(deployment),
                    "tier": self._infer_tier(deployment),
                }
                services.append(service)
                
                logger.debug("deployment_processed",
                           name=deployment.metadata.name,
                           namespace=namespace,
                           replicas=service["replicas"],
                           tier=service["tier"],
                           critical=service["critical"])
                
            logger.info("deployments_fetched", 
                       namespace=namespace, 
                       count=len(services))
            
            return services
            
        except Exception as e:
            error_msg = f"Failed to fetch deployments from namespace {namespace}: {str(e)}"
            logger.error("deployment_fetch_failed", namespace=namespace, error=str(e))
            self.warnings.append(error_msg)
            return []

    def _fetch_statefulsets(self, namespace: str) -> List[Dict[str, Any]]:
        """Fetch all statefulsets in a namespace"""
        try:
            statefulsets = self.v1_apps.list_namespaced_stateful_set(namespace)
            services = []
            
            for sts in statefulsets.items:
                service_info = self._find_service_for_statefulset(namespace, sts)
                
                service = {
                    "name": sts.metadata.name,
                    "namespace": namespace,
                    "type": "statefulset",
                    "replicas": sts.spec.replicas or 1,
                    "labels": sts.metadata.labels or {},
                    "selector": sts.spec.selector.match_labels or {},
                    "containers": self._extract_container_info(sts.spec.template.spec.containers),
                    "service": service_info,
                    "critical": True,  # StatefulSets are usually critical (databases, etc.)
                    "tier": "database",  # Most StatefulSets are data tier
                }
                services.append(service)
                
                logger.debug("statefulset_processed",
                           name=sts.metadata.name,
                           namespace=namespace,
                           replicas=service["replicas"])
                
            logger.info("statefulsets_fetched", 
                       namespace=namespace, 
                       count=len(services))
            
            return services
            
        except Exception as e:
            error_msg = f"Failed to fetch statefulsets from namespace {namespace}: {str(e)}"
            logger.error("statefulset_fetch_failed", namespace=namespace, error=str(e))
            self.warnings.append(error_msg)
            return []

    def _find_service_for_deployment(self, namespace: str, deployment) -> Optional[Dict[str, Any]]:
        """Find Kubernetes service that exposes this deployment"""
        try:
            services = self.v1_core.list_namespaced_service(namespace)
            deployment_labels = deployment.spec.selector.match_labels or {}
            
            for svc in services.items:
                svc_selector = svc.spec.selector or {}
                # Check if service selector matches deployment labels
                if self._labels_match(svc_selector, deployment_labels):
                    service_info = {
                        "name": svc.metadata.name,
                        "type": svc.spec.type,
                        "ports": [{"port": p.port, "targetPort": p.target_port} for p in svc.spec.ports or []],
                        "cluster_ip": svc.spec.cluster_ip,
                    }
                    
                    logger.debug("service_matched_to_deployment",
                               deployment=deployment.metadata.name,
                               service=svc.metadata.name,
                               namespace=namespace)
                    
                    return service_info
            
            logger.debug("no_service_found_for_deployment",
                        deployment=deployment.metadata.name,
                        namespace=namespace)
            return None
            
        except Exception as e:
            logger.warning("service_lookup_failed",
                          deployment=deployment.metadata.name,
                          namespace=namespace,
                          error=str(e))
            return None

    def _find_service_for_statefulset(self, namespace: str, sts) -> Optional[Dict[str, Any]]:
        """Find Kubernetes service that exposes this statefulset"""
        try:
            services = self.v1_core.list_namespaced_service(namespace)
            sts_labels = sts.spec.selector.match_labels or {}
            
            for svc in services.items:
                svc_selector = svc.spec.selector or {}
                if self._labels_match(svc_selector, sts_labels):
                    service_info = {
                        "name": svc.metadata.name,
                        "type": svc.spec.type,
                        "ports": [{"port": p.port, "targetPort": p.target_port} for p in svc.spec.ports or []],
                        "cluster_ip": svc.spec.cluster_ip,
                    }
                    
                    logger.debug("service_matched_to_statefulset",
                               statefulset=sts.metadata.name,
                               service=svc.metadata.name,
                               namespace=namespace)
                    
                    return service_info
            
            logger.debug("no_service_found_for_statefulset",
                        statefulset=sts.metadata.name,
                        namespace=namespace)
            return None
            
        except Exception as e:
            logger.warning("service_lookup_failed",
                          statefulset=sts.metadata.name,
                          namespace=namespace,
                          error=str(e))
            return None

    def _labels_match(self, selector: Dict[str, str], labels: Dict[str, str]) -> bool:
        """Check if selector matches labels"""
        if not selector:
            return False
        return all(labels.get(k) == v for k, v in selector.items())

    def _extract_container_info(self, containers) -> List[Dict[str, Any]]:
        """Extract container information"""
        container_info = []
        for container in containers:
            info = {
                "name": container.name,
                "image": container.image,
                "ports": [p.container_port for p in container.ports or []],
                "env_vars": {env.name: env.value for env in container.env or [] if env.value},
            }
            container_info.append(info)
        return container_info

    def _infer_criticality(self, resource) -> bool:
        """Infer if a service is critical based on labels, name, etc."""
        name = resource.metadata.name.lower()
        labels = resource.metadata.labels or {}
        
        # Critical indicators
        critical_keywords = ['frontend', 'api', 'gateway', 'auth', 'payment', 'order']
        critical_labels = ['critical', 'production', 'important']
        
        # Check name
        if any(keyword in name for keyword in critical_keywords):
            return True
            
        # Check labels
        if any(label in str(labels).lower() for label in critical_labels):
            return True
            
        # High replica count suggests importance
        replicas = getattr(resource.spec, 'replicas', 1) or 1
        if replicas > 2:
            return True
            
        return False

    def _infer_tier(self, resource) -> str:
        """Infer service tier based on name and labels"""
        name = resource.metadata.name.lower()
        labels = resource.metadata.labels or {}
        
        # Check explicit tier label
        if 'tier' in labels:
            return labels['tier']
            
        # Infer from name
        if any(keyword in name for keyword in ['frontend', 'ui', 'web']):
            return 'frontend'
        elif any(keyword in name for keyword in ['api', 'backend', 'service']):
            return 'backend'
        elif any(keyword in name for keyword in ['db', 'database', 'redis', 'mongo', 'postgres']):
            return 'database'
        elif any(keyword in name for keyword in ['queue', 'worker', 'job']):
            return 'worker'
        else:
            return 'backend'  # Default

    def _infer_dependencies(self, services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Infer service dependencies from environment variables and naming patterns"""
        dependency_count = 0
        
        for service in services:
            dependencies = []
            
            # Check environment variables for service references
            for container in service.get('containers', []):
                env_vars = container.get('env_vars', {})
                
                for env_name, env_value in env_vars.items():
                    if env_value:
                        # Look for service names in env vars
                        for other_service in services:
                            if (other_service['name'] != service['name'] and 
                                other_service['name'].lower() in env_value.lower()):
                                dependencies.append(other_service['name'])
            
            # Infer common patterns (frontend -> backend -> database)
            service_tier = service.get('tier', '')
            if service_tier == 'frontend':
                # Frontend typically depends on backend/api services
                backend_services = [s['name'] for s in services 
                                 if s['tier'] in ['backend', 'api'] and s['name'] != service['name']]
                dependencies.extend(backend_services)
            elif service_tier == 'backend':
                # Backend typically depends on databases
                db_services = [s['name'] for s in services 
                             if s['tier'] == 'database' and s['name'] != service['name']]
                dependencies.extend(db_services)
            
            service['dependencies'] = list(set(dependencies))  # Remove duplicates
            dependency_count += len(service['dependencies'])
            
            if service['dependencies']:
                logger.debug("dependencies_inferred",
                           service=service['name'],
                           dependencies=service['dependencies'])
        
        logger.info("dependency_inference_completed",
                   total_dependencies=dependency_count)
        
        return services

    def _build_service_relationships(self, services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build service relationship graph"""
        relationships = []
        
        for service in services:
            for dep in service.get('dependencies', []):
                relationships.append({
                    "source": service['name'],
                    "target": dep,
                    "type": "depends_on",
                    "namespace": service['namespace']
                })
        
        logger.info("service_relationships_built", count=len(relationships))
        return relationships

    def _get_mock_topology(self) -> Dict[str, Any]:
        """Return mock topology for testing"""
        logger.info("returning_mock_topology")
        
        return {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "cluster": {"kubernetes_version": "v1.28.0", "provider": "mock"},
                "namespaces_scanned": ["demo"],
                "total_services": 3,
                "errors": [],
                "warnings": [],
                "suggestions": [],
            },
            "services": [
                {
                    "name": "frontend",
                    "namespace": "demo",
                    "type": "deployment",
                    "replicas": 2,
                    "critical": True,
                    "tier": "frontend",
                    "dependencies": ["api"],
                    "labels": {"app": "frontend", "tier": "frontend"},
                },
                {
                    "name": "api",
                    "namespace": "demo", 
                    "type": "deployment",
                    "replicas": 2,
                    "critical": True,
                    "tier": "backend",
                    "dependencies": ["redis"],
                    "labels": {"app": "api", "tier": "backend"},
                },
                {
                    "name": "redis",
                    "namespace": "demo",
                    "type": "deployment", 
                    "replicas": 1,
                    "critical": True,
                    "tier": "database",
                    "dependencies": [],
                    "labels": {"app": "redis", "tier": "database"},
                }
            ],
            "relationships": [
                {"source": "frontend", "target": "api", "type": "depends_on", "namespace": "demo"},
                {"source": "api", "target": "redis", "type": "depends_on", "namespace": "demo"}
            ]
        }

    def run(self, namespaces: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Main method to fetch inventory from Kubernetes cluster.
        
        Args:
            namespaces: Optional list of namespaces to scan. If None, auto-discovers.
            
        Returns:
            Dictionary containing unified service graph
        """
        logger.info("inventory_fetch_started", mock_mode=self.mock_mode)

        try:
            if self.mock_mode:
                return self._get_mock_topology()

            # Initialize Kubernetes clients
            self._init_kubernetes_clients()

            # Get cluster information
            cluster_info = self._get_cluster_info()

            # Discover namespaces if not provided
            if namespaces is None:
                namespaces = self._discover_namespaces()
            
            logger.info("scanning_namespaces", namespaces=namespaces)

            # Fetch services from each namespace
            all_services = []
            for namespace in namespaces:
                try:
                    # Fetch deployments and statefulsets
                    deployments = self._fetch_deployments(namespace)
                    statefulsets = self._fetch_statefulsets(namespace)
                    
                    namespace_services = deployments + statefulsets
                    all_services.extend(namespace_services)
                    
                    logger.info("namespace_scan_completed",
                               namespace=namespace,
                               deployments=len(deployments),
                               statefulsets=len(statefulsets),
                               total=len(namespace_services))
                               
                except Exception as e:
                    error_msg = f"Failed to fetch from namespace {namespace}: {str(e)}"
                    self.warnings.append(error_msg)
                    logger.error("namespace_scan_failed", 
                                namespace=namespace, 
                                error=str(e))

            # Infer service dependencies
            all_services = self._infer_dependencies(all_services)

            # Create unified topology
            topology = {
                "metadata": {
                    "generated_at": datetime.utcnow().isoformat(),
                    "cluster": cluster_info,
                    "namespaces_scanned": namespaces,
                    "total_services": len(all_services),
                    "errors": self.errors,
                    "warnings": self.warnings,
                    "suggestions": self.suggestions,
                },
                "services": all_services,
                "relationships": self._build_service_relationships(all_services),
            }

            # Print summary
            self._print_summary(topology)

            logger.info("inventory_fetch_completed",
                       total_services=len(all_services),
                       namespaces_count=len(namespaces),
                       relationships_count=len(topology["relationships"]),
                       errors_count=len(self.errors),
                       warnings_count=len(self.warnings))

            return topology

        except Exception as e:
            error_msg = f"Inventory fetch failed: {str(e)}"
            logger.error("inventory_fetch_failed", error=str(e))
            raise InventoryFetchError(error_msg)

    def _print_summary(self, topology: Dict[str, Any]):
        """Print a human-readable summary of discovered services"""
        services = topology.get("services", [])
        relationships = topology.get("relationships", [])
        
        print(f"\nDiscovered {len(services)} services across {len(topology['metadata']['namespaces_scanned'])} namespaces:")
        
        # Group by namespace and tier
        by_namespace = {}
        for service in services:
            ns = service['namespace']
            if ns not in by_namespace:
                by_namespace[ns] = {}
            
            tier = service.get('tier', 'unknown')
            if tier not in by_namespace[ns]:
                by_namespace[ns][tier] = []
            by_namespace[ns][tier].append(service)
        
        for namespace, tiers in by_namespace.items():
            print(f"\n  Namespace: {namespace}")
            for tier, tier_services in tiers.items():
                print(f"    {tier}: {', '.join([s['name'] for s in tier_services])}")
        
        if relationships:
            print(f"\nDiscovered {len(relationships)} service relationships:")
            for rel in relationships[:5]:  # Show first 5
                print(f"    {rel['source']} -> {rel['target']}")
            if len(relationships) > 5:
                print(f"    ... and {len(relationships) - 5} more")
        
        if self.warnings:
            print(f"\nWarnings ({len(self.warnings)}):")
            for warning in self.warnings[:3]:
                print(f"    {warning}")
            if len(self.warnings) > 3:
                print(f"    ... and {len(self.warnings) - 3} more")
