"""
Kubernetes Inventory Fetch Tool

Discovers services, deployments, statefulsets, and other resources
across configured namespaces and creates a unified service graph.
"""

import json
import yaml
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import os

import structlog
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config import kube_config

logger = structlog.get_logger()


class InventoryFetchError(Exception):
    """Custom exception for inventory fetch errors"""

    pass


class InventoryFetchTool:
    """
    Fetches Kubernetes inventory and creates a unified service graph.

    Features:
    - Robust error handling with helpful suggestions
    - Graceful degradation when services are unavailable
    - Comprehensive validation and hints
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

        if not self.mock_mode:
            self._init_kubernetes_client()
        else:
            logger.info("Running in mock mode - no Kubernetes connection required")

    def _init_kubernetes_client(self):
        """Initialize Kubernetes API clients with comprehensive error handling"""
        try:
            # Check if kubectl is available
            if not self._check_kubectl_available():
                raise InventoryFetchError("kubectl is not available in PATH")

            # Check if kubeconfig exists and is valid
            kubeconfig_path = self._get_kubeconfig_path()
            if not self._validate_kubeconfig(kubeconfig_path):
                raise InventoryFetchError(f"Invalid kubeconfig at {kubeconfig_path}")

            # Load kubeconfig
            config.load_kube_config()

            # Create API clients
            self.v1_apps = client.AppsV1Api()
            self.v1_core = client.CoreV1Api()
            self.v1_networking = client.NetworkingV1Api()

            # Test connection
            self._test_kubernetes_connection()

            logger.info("Kubernetes client initialized successfully")

        except InventoryFetchError:
            raise
        except Exception as e:
            error_msg = f"Failed to initialize Kubernetes client: {str(e)}"
            suggestions = self._get_connection_suggestions(str(e))
            raise InventoryFetchError(f"{error_msg}\n\nSuggestions:\n{suggestions}")

    def _check_kubectl_available(self) -> bool:
        """Check if kubectl is available in PATH"""
        try:
            result = subprocess.run(
                ["kubectl", "version", "--client"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _get_kubeconfig_path(self) -> str:
        """Get the path to kubeconfig file"""
        # Check environment variable first
        kubeconfig = os.getenv("KUBECONFIG")
        if kubeconfig:
            return kubeconfig

        # Default location
        home = os.path.expanduser("~")
        return os.path.join(home, ".kube", "config")

    def _validate_kubeconfig(self, kubeconfig_path: str) -> bool:
        """Validate kubeconfig file exists and is readable"""
        if not os.path.exists(kubeconfig_path):
            self.suggestions.append(f"Kubeconfig not found at {kubeconfig_path}")
            self.suggestions.append(
                "Run: aws eks update-kubeconfig --region <region> --name <cluster-name>"
            )
            return False

        try:
            with open(kubeconfig_path, "r") as f:
                yaml.safe_load(f)
            return True
        except Exception as e:
            self.suggestions.append(f"Invalid kubeconfig format: {str(e)}")
            return False

    def _test_kubernetes_connection(self):
        """Test connection to Kubernetes cluster"""
        try:
            # Try to get cluster info
            version_api = client.VersionApi()
            version_info = version_api.get_code()
            logger.info("Connected to cluster", version=version_info.git_version)
        except ApiException as e:
            if e.status == 401:
                raise InventoryFetchError(
                    "Authentication failed. Check your kubeconfig credentials."
                )
            elif e.status == 403:
                raise InventoryFetchError("Access denied. Check your RBAC permissions.")
            else:
                raise InventoryFetchError(f"Failed to connect to cluster: {e.reason}")
        except Exception as e:
            raise InventoryFetchError(f"Failed to test cluster connection: {str(e)}")

    def _get_connection_suggestions(self, error: str) -> str:
        """Get helpful suggestions based on the error"""
        suggestions = []

        if "kubeconfig" in error.lower():
            suggestions.extend(
                [
                    "1. Check if kubectl is installed: brew install kubectl",
                    "2. Configure kubectl for your cluster:",
                    "   - AWS EKS: aws eks update-kubeconfig --region <region> --name <cluster-name>",
                    "   - GKE: gcloud container clusters get-credentials <cluster-name> --region <region>",
                    "   - AKS: az aks get-credentials --resource-group <rg> --name <cluster-name>",
                    "3. Verify cluster is running: kubectl cluster-info",
                ]
            )
        elif "authentication" in error.lower():
            suggestions.extend(
                [
                    "1. Check your AWS credentials: aws sts get-caller-identity",
                    "2. Update kubeconfig: aws eks update-kubeconfig --region <region> --name <cluster-name>",
                    "3. Check IAM permissions for EKS access",
                ]
            )
        elif "connection" in error.lower():
            suggestions.extend(
                [
                    "1. Check if cluster is running: kubectl cluster-info",
                    "2. Verify network connectivity to cluster endpoint",
                    "3. Check if you're on the correct VPN if required",
                ]
            )

        return "\n".join(suggestions)

    def run(self) -> Dict[str, Any]:
        """
        Main method to fetch inventory from Kubernetes cluster.

        Returns:
            Dictionary containing unified service graph
        """
        logger.info("Starting inventory fetch", mock_mode=self.mock_mode)

        try:
            if self.mock_mode:
                return self._get_mock_topology(stack_file)

            # Load configuration
            config_data = self._load_config(stack_file)
            k8s_config = config_data.get("k8s", {})

            # Validate configuration
            self._validate_config(k8s_config)

            # Get namespaces to scan
            namespaces = k8s_config.get("namespaces", ["default"])
            target_services = k8s_config.get("target_services", [])

            # Fetch cluster information
            cluster_info = self._get_cluster_info()

            # Fetch services from each namespace
            services = []
            for namespace in namespaces:
                try:
                    namespace_services = self._fetch_namespace_services(
                        namespace, target_services
                    )
                    services.extend(namespace_services)
                    logger.info(
                        "Fetched services from namespace",
                        namespace=namespace,
                        count=len(namespace_services),
                    )
                except Exception as e:
                    error_msg = f"Failed to fetch from namespace {namespace}: {str(e)}"
                    self.warnings.append(error_msg)
                    logger.warning(error_msg)

            # Create unified topology
            topology = {
                "metadata": {
                    "generated_at": datetime.utcnow().isoformat(),
                    "cluster": cluster_info,
                    "namespaces_scanned": namespaces,
                    "total_services": len(services),
                    "errors": self.errors,
                    "warnings": self.warnings,
                    "suggestions": self.suggestions,
                },
                "services": services,
                "relationships": self._build_service_relationships(services),
            }

            # Print summary
            self._print_summary(topology)

            logger.info(
                "Inventory fetch completed",
                total_services=len(services),
                namespaces=len(namespaces),
                errors=len(self.errors),
                warnings=len(self.warnings),
            )

            return topology

        except Exception as e:
            logger.error("Inventory fetch failed", error=str(e))
            raise InventoryFetchError(f"Inventory fetch failed: {str(e)}")

    def _validate_config(self, k8s_config: Dict[str, Any]):
        """Validate Kubernetes configuration"""
        if not k8s_config:
            self.warnings.append("No Kubernetes configuration found in stack.yaml")
            self.suggestions.append("Add k8s configuration to stack.yaml")
            return

        namespaces = k8s_config.get("namespaces", [])
        if not namespaces:
            self.warnings.append("No namespaces configured")
            self.suggestions.append("Add namespaces to k8s.namespaces in stack.yaml")

    def _load_config(self, stack_file: Path) -> Dict[str, Any]:
        """Load and parse stack configuration file with error handling"""
        try:
            if not stack_file.exists():
                raise InventoryFetchError(
                    f"Stack configuration file not found: {stack_file}"
                )

            with open(stack_file, "r") as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                raise InventoryFetchError("Stack configuration file is empty")

            return config_data

        except yaml.YAMLError as e:
            raise InventoryFetchError(f"Invalid YAML in stack configuration: {str(e)}")
        except Exception as e:
            raise InventoryFetchError(f"Failed to load stack configuration: {str(e)}")

    def _get_cluster_info(self) -> Dict[str, Any]:
        """Get basic cluster information with error handling"""
        try:
            # Get cluster version
            version_api = client.VersionApi()
            version_info = version_api.get_code()

            # Get nodes info
            nodes = self.v1_core.list_node()

            cluster_info = {
                "kubernetes_version": version_info.git_version,
                "platform": version_info.platform,
                "node_count": len(nodes.items),
                "provider": self._detect_provider(nodes.items),
            }

            logger.info(
                "Cluster info retrieved",
                version=version_info.git_version,
                nodes=len(nodes.items),
                provider=cluster_info["provider"],
            )

            return cluster_info

        except Exception as e:
            error_msg = f"Failed to get cluster info: {str(e)}"
            self.warnings.append(error_msg)
            logger.warning(error_msg)
            return {"error": str(e)}

    def _detect_provider(self, nodes: List) -> str:
        """Detect cloud provider from node labels"""
        for node in nodes:
            labels = node.metadata.labels or {}
            if "eks.amazonaws.com" in str(labels):
                return "aws-eks"
            elif "gke.io" in str(labels):
                return "gcp-gke"
            elif "aks.azure.com" in str(labels):
                return "azure-aks"
        return "unknown"

    def _fetch_namespace_services(
        self, namespace: str, target_services: List[Dict]
    ) -> List[Dict]:
        """Fetch all services from a specific namespace with comprehensive error handling"""
        services = []

        # Check if namespace exists
        try:
            self.v1_core.read_namespace(name=namespace)
        except ApiException as e:
            if e.status == 404:
                error_msg = f"Namespace '{namespace}' not found"
                self.warnings.append(error_msg)
                self.suggestions.append(
                    f"Create namespace: kubectl create namespace {namespace}"
                )
                return services
            else:
                error_msg = f"Failed to access namespace '{namespace}': {e.reason}"
                self.warnings.append(error_msg)
                return services

        # Fetch Deployments
        try:
            deployments = self.v1_apps.list_namespaced_deployment(namespace=namespace)
            for deployment in deployments.items:
                service_info = self._extract_deployment_info(deployment, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            error_msg = f"Failed to fetch deployments from {namespace}: {e.reason}"
            self.warnings.append(error_msg)
        except Exception as e:
            error_msg = (
                f"Unexpected error fetching deployments from {namespace}: {str(e)}"
            )
            self.warnings.append(error_msg)

        # Fetch StatefulSets
        try:
            statefulsets = self.v1_apps.list_namespaced_stateful_set(
                namespace=namespace
            )
            for statefulset in statefulsets.items:
                service_info = self._extract_statefulset_info(statefulset, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            error_msg = f"Failed to fetch statefulsets from {namespace}: {e.reason}"
            self.warnings.append(error_msg)
        except Exception as e:
            error_msg = (
                f"Unexpected error fetching statefulsets from {namespace}: {str(e)}"
            )
            self.warnings.append(error_msg)

        # Fetch DaemonSets
        try:
            daemonsets = self.v1_apps.list_namespaced_daemon_set(namespace=namespace)
            for daemonset in daemonsets.items:
                service_info = self._extract_daemonset_info(daemonset, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            error_msg = f"Failed to fetch daemonsets from {namespace}: {e.reason}"
            self.warnings.append(error_msg)
        except Exception as e:
            error_msg = (
                f"Unexpected error fetching daemonsets from {namespace}: {str(e)}"
            )
            self.warnings.append(error_msg)

        # Fetch Services
        try:
            k8s_services = self.v1_core.list_namespaced_service(namespace=namespace)
            for k8s_service in k8s_services.items:
                service_info = self._extract_service_info(k8s_service, namespace)
                if service_info:
                    services.append(service_info)
        except ApiException as e:
            error_msg = f"Failed to fetch services from {namespace}: {e.reason}"
            self.warnings.append(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error fetching services from {namespace}: {str(e)}"
            self.warnings.append(error_msg)

        return services

    def _extract_deployment_info(
        self, deployment, namespace: str
    ) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a Deployment with error handling"""
        try:
            metadata = deployment.metadata
            spec = deployment.spec
            status = deployment.status

            # Get resource requirements
            resources = self._extract_resource_requirements(
                spec.template.spec.containers
            )

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
                    "available": (
                        status.available_replicas if status.available_replicas else 0
                    ),
                    "ready": status.ready_replicas if status.ready_replicas else 0,
                },
                "labels": dict(labels),
                "annotations": dict(annotations),
                "resources": resources,
                "containers": [
                    {
                        "name": container.name,
                        "image": container.image,
                        "ports": (
                            [
                                {
                                    "container_port": port.container_port,
                                    "protocol": port.protocol,
                                }
                                for port in container.ports
                            ]
                            if container.ports
                            else []
                        ),
                    }
                    for container in spec.template.spec.containers
                ],
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": (
                    metadata.creation_timestamp.isoformat()
                    if metadata.creation_timestamp
                    else None
                ),
            }
        except Exception as e:
            error_msg = f"Failed to extract deployment info for {deployment.metadata.name}: {str(e)}"
            self.warnings.append(error_msg)
            logger.warning(error_msg)
            return None

    def _extract_statefulset_info(
        self, statefulset, namespace: str
    ) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a StatefulSet with error handling"""
        try:
            metadata = statefulset.metadata
            spec = statefulset.spec
            status = statefulset.status

            resources = self._extract_resource_requirements(
                spec.template.spec.containers
            )
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
                    "available": (
                        status.available_replicas if status.available_replicas else 0
                    ),
                    "ready": status.ready_replicas if status.ready_replicas else 0,
                },
                "labels": dict(labels),
                "annotations": dict(annotations),
                "resources": resources,
                "containers": [
                    {
                        "name": container.name,
                        "image": container.image,
                        "ports": (
                            [
                                {
                                    "container_port": port.container_port,
                                    "protocol": port.protocol,
                                }
                                for port in container.ports
                            ]
                            if container.ports
                            else []
                        ),
                    }
                    for container in spec.template.spec.containers
                ],
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": (
                    metadata.creation_timestamp.isoformat()
                    if metadata.creation_timestamp
                    else None
                ),
            }
        except Exception as e:
            error_msg = f"Failed to extract statefulset info for {statefulset.metadata.name}: {str(e)}"
            self.warnings.append(error_msg)
            logger.warning(error_msg)
            return None

    def _extract_daemonset_info(
        self, daemonset, namespace: str
    ) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a DaemonSet with error handling"""
        try:
            metadata = daemonset.metadata
            spec = daemonset.spec
            status = daemonset.status

            resources = self._extract_resource_requirements(
                spec.template.spec.containers
            )
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
                    "ready": status.number_ready,
                },
                "labels": dict(labels),
                "annotations": dict(annotations),
                "resources": resources,
                "containers": [
                    {
                        "name": container.name,
                        "image": container.image,
                        "ports": (
                            [
                                {
                                    "container_port": port.container_port,
                                    "protocol": port.protocol,
                                }
                                for port in container.ports
                            ]
                            if container.ports
                            else []
                        ),
                    }
                    for container in spec.template.spec.containers
                ],
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": (
                    metadata.creation_timestamp.isoformat()
                    if metadata.creation_timestamp
                    else None
                ),
            }
        except Exception as e:
            error_msg = f"Failed to extract daemonset info for {daemonset.metadata.name}: {str(e)}"
            self.warnings.append(error_msg)
            logger.warning(error_msg)
            return None

    def _extract_service_info(
        self, k8s_service, namespace: str
    ) -> Optional[Dict[str, Any]]:
        """Extract relevant information from a Service with error handling"""
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
                "ports": (
                    [
                        {
                            "port": port.port,
                            "target_port": port.target_port,
                            "protocol": port.protocol,
                        }
                        for port in spec.ports
                    ]
                    if spec.ports
                    else []
                ),
                "selector": dict(spec.selector) if spec.selector else {},
                "labels": dict(labels),
                "annotations": dict(annotations),
                "critical": self._is_critical_service(metadata.name, namespace),
                "created_at": (
                    metadata.creation_timestamp.isoformat()
                    if metadata.creation_timestamp
                    else None
                ),
            }
        except Exception as e:
            error_msg = f"Failed to extract service info for {k8s_service.metadata.name}: {str(e)}"
            self.warnings.append(error_msg)
            logger.warning(error_msg)
            return None

    def _extract_resource_requirements(self, containers: List) -> Dict[str, Any]:
        """Extract resource requirements from containers with error handling"""
        try:
            total_requests = {"cpu": "0", "memory": "0"}
            total_limits = {"cpu": "0", "memory": "0"}

            for container in containers:
                if container.resources:
                    # Sum up requests
                    if container.resources.requests:
                        for resource, value in container.resources.requests.items():
                            if resource in total_requests:
                                # Simple addition (in real implementation, you'd want proper resource arithmetic)
                                total_requests[resource] = str(
                                    float(total_requests[resource]) + float(value)
                                )

                    # Sum up limits
                    if container.resources.limits:
                        for resource, value in container.resources.limits.items():
                            if resource in total_limits:
                                total_limits[resource] = str(
                                    float(total_limits[resource]) + float(value)
                                )

            return {"requests": total_requests, "limits": total_limits}
        except Exception as e:
            logger.warning("Failed to extract resource requirements", error=str(e))
            return {
                "requests": {"cpu": "0", "memory": "0"},
                "limits": {"cpu": "0", "memory": "0"},
            }

    def _is_critical_service(self, name: str, namespace: str) -> bool:
        """Determine if a service is critical based on configuration or labels"""
        # This could be enhanced with more sophisticated logic
        critical_keywords = [
            "redis",
            "mysql",
            "postgres",
            "database",
            "cache",
            "frontend",
            "api",
        ]
        return any(keyword in name.lower() for keyword in critical_keywords)

    def _build_service_relationships(self, services: List[Dict]) -> List[Dict]:
        """Build relationships between services based on selectors and dependencies"""
        try:
            relationships = []

            # Find service-to-service relationships
            for service in services:
                if service["type"] == "service" and service.get("selector"):
                    selector = service["selector"]

                    # Find deployments/statefulsets that match this selector
                    for target in services:
                        if target["type"] in ["deployment", "statefulset", "daemonset"]:
                            if target["namespace"] == service["namespace"]:
                                # Check if labels match selector
                                if self._labels_match_selector(
                                    target.get("labels", {}), selector
                                ):
                                    relationships.append(
                                        {
                                            "from": service["id"],
                                            "to": target["id"],
                                            "type": "selector_match",
                                            "namespace": service["namespace"],
                                        }
                                    )

            return relationships
        except Exception as e:
            logger.warning("Failed to build service relationships", error=str(e))
            return []

    def _labels_match_selector(
        self, labels: Dict[str, str], selector: Dict[str, str]
    ) -> bool:
        """Check if labels match a selector"""
        try:
            for key, value in selector.items():
                if key not in labels or labels[key] != value:
                    return False
            return True
        except Exception:
            return False

    def _print_summary(self, topology: Dict[str, Any]):
        """Print a user-friendly summary of the inventory fetch"""
        metadata = topology.get("metadata", {})
        services = topology.get("services", [])

        print("\n" + "=" * 60)
        print("🏗️  INFRASTRUCTURE INVENTORY SUMMARY")
        print("=" * 60)

        # Cluster info
        cluster_info = metadata.get("cluster", {})
        if "error" not in cluster_info:
            print(f"📊 Cluster: {cluster_info.get('kubernetes_version', 'Unknown')}")
            print(f"   Provider: {cluster_info.get('provider', 'Unknown')}")
            print(f"   Nodes: {cluster_info.get('node_count', 0)}")
        else:
            print(f"⚠️  Cluster info unavailable: {cluster_info['error']}")

        # Services summary
        services_by_type = {}
        for service in services:
            service_type = service.get("type", "unknown")
            if service_type not in services_by_type:
                services_by_type[service_type] = []
            services_by_type[service_type].append(service)

        print(f"\n📦 Services Found: {len(services)}")
        for service_type, type_services in services_by_type.items():
            print(f"   • {service_type.title()}: {len(type_services)}")

        # Namespaces
        namespaces = metadata.get("namespaces_scanned", [])
        print(f"\n🏷️  Namespaces Scanned: {', '.join(namespaces)}")

        # Critical services
        critical_services = [s for s in services if s.get("critical", False)]
        if critical_services:
            print(f"\n🔴 Critical Services: {len(critical_services)}")
            for service in critical_services[:5]:  # Show first 5
                print(f"   • {service['name']} ({service['type']})")
            if len(critical_services) > 5:
                print(f"   ... and {len(critical_services) - 5} more")

        # Warnings and suggestions
        warnings = metadata.get("warnings", [])
        suggestions = metadata.get("suggestions", [])

        if warnings:
            print(f"\n⚠️  Warnings ({len(warnings)}):")
            for warning in warnings[:3]:  # Show first 3
                print(f"   • {warning}")
            if len(warnings) > 3:
                print(f"   ... and {len(warnings) - 3} more warnings")

        if suggestions:
            print(f"\n💡 Suggestions ({len(suggestions)}):")
            for suggestion in suggestions[:3]:  # Show first 3
                print(f"   • {suggestion}")
            if len(suggestions) > 3:
                print(f"   ... and {len(suggestions) - 3} more suggestions")

        print("\n" + "=" * 60)

    def save_topology(
        self, topology: Dict[str, Any], output_path: Path = Path("context/topo.json")
    ):
        """Save topology to JSON file"""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w") as f:
                json.dump(topology, f, indent=2, default=str)

            logger.info("Topology saved", path=str(output_path))
            return output_path
        except Exception as e:
            error_msg = f"Failed to save topology: {str(e)}"
            logger.error(error_msg)
            raise InventoryFetchError(error_msg)

    def _get_mock_topology(self) -> Dict[str, Any]:
        """Get mock topology for testing without Kubernetes connection"""
        return {
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "cluster": {
                    "kubernetes_version": "v1.28.0",
                    "provider": "mock",
                    "node_count": 3,
                },
                "namespaces_scanned": ["sock-shop"],
                "total_services": 13,
                "mock_mode": True,
            },
            "services": [
                {
                    "id": "sock-shop/front-end",
                    "name": "front-end",
                    "namespace": "sock-shop",
                    "env": "k8s",
                    "type": "deployment",
                    "replicas": {"desired": 2, "available": 2, "ready": 2},
                    "critical": True,
                },
                {
                    "id": "sock-shop/redis",
                    "name": "redis",
                    "namespace": "sock-shop",
                    "env": "k8s",
                    "type": "statefulset",
                    "replicas": {"desired": 1, "available": 1, "ready": 1},
                    "critical": True,
                },
            ],
            "relationships": [],
        }
