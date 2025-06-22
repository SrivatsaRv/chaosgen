"""
Basic tests for the chaos engineering agent.

Tests core functionality without requiring actual Kubernetes cluster.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from tools.inventory_fetch import InventoryFetchTool
from tools.experiment_designer import ExperimentDesigner
from tools.executor_adapter import ExecutorAdapter
from tools.post_run_narrator import PostRunNarrator


class TestInventoryFetch:
    """Test inventory fetch functionality"""
    
    def test_load_config(self):
        """Test configuration loading"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""
k8s:
  namespaces:
    - default
    - sock-shop
  target_services:
    - name: redis
      namespace: sock-shop
      type: statefulset
            """)
            config_path = f.name
        
        try:
            tool = InventoryFetchTool()
            config = tool._load_config(Path(config_path))
            
            assert 'k8s' in config
            assert 'namespaces' in config['k8s']
            assert 'default' in config['k8s']['namespaces']
            assert 'sock-shop' in config['k8s']['namespaces']
            
        finally:
            Path(config_path).unlink()
    
    @patch('tools.inventory_fetch.client')
    def test_mock_inventory_fetch(self, mock_client):
        """Test inventory fetch with mocked Kubernetes client"""
        # Mock Kubernetes API responses
        mock_deployment = Mock()
        mock_deployment.metadata.name = "frontend"
        mock_deployment.metadata.namespace = "sock-shop"
        mock_deployment.spec.replicas = 2
        mock_deployment.status.available_replicas = 2
        mock_deployment.status.ready_replicas = 2
        
        mock_apps_api = Mock()
        mock_apps_api.list_namespaced_deployment.return_value.items = [mock_deployment]
        mock_apps_api.list_namespaced_stateful_set.return_value.items = []
        mock_apps_api.list_namespaced_daemon_set.return_value.items = []
        
        mock_client.AppsV1Api.return_value = mock_apps_api
        
        # Test inventory fetch
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""
k8s:
  namespaces:
    - sock-shop
            """)
            config_path = f.name
        
        try:
            tool = InventoryFetchTool()
            topology = tool.run(Path(config_path))
            
            assert 'services' in topology
            assert len(topology['services']) > 0
            
            # Check that we found the frontend deployment
            frontend_service = next(
                (s for s in topology['services'] if s['name'] == 'frontend'), 
                None
            )
            assert frontend_service is not None
            assert frontend_service['type'] == 'deployment'
            assert frontend_service['namespace'] == 'sock-shop'
            
        finally:
            Path(config_path).unlink()


class TestExperimentDesigner:
    """Test experiment design functionality"""
    
    def test_experiment_spec_validation(self):
        """Test experiment specification validation"""
        from tools.experiment_designer import ExperimentSpec
        
        # Valid spec
        valid_spec = {
            "title": "Redis Pod Kill",
            "description": "Test Redis failover",
            "env": "k8s",
            "action": "pod-kill",
            "target_selector": {
                "namespace": "sock-shop",
                "label_selector": "app=redis"
            },
            "parameters": {
                "duration": "60s",
                "intensity": 0.5
            },
            "abort_threshold": {
                "metric": "error_rate",
                "value": 0.05,
                "operator": ">"
            },
            "expected_impact": "Redis failover test",
            "risk_level": "medium",
            "chaos_engine": "litmuschaos"
        }
        
        spec = ExperimentSpec(**valid_spec)
        assert spec.title == "Redis Pod Kill"
        assert spec.action == "pod-kill"
        assert spec.risk_level == "medium"
    
    def test_experiment_spec_invalid(self):
        """Test invalid experiment specification"""
        from tools.experiment_designer import ExperimentSpec
        
        # Invalid spec (missing required fields)
        invalid_spec = {
            "title": "Redis Pod Kill",
            # Missing required fields
        }
        
        with pytest.raises(Exception):
            ExperimentSpec(**invalid_spec)
    
    @patch('tools.experiment_designer.OpenAI')
    def test_mock_experiment_design(self, mock_openai):
        """Test experiment design with mocked LLM"""
        # Mock LLM response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = json.dumps([
            {
                "title": "Redis Pod Kill",
                "description": "Test Redis failover mechanism",
                "env": "k8s",
                "action": "pod-kill",
                "target_selector": {
                    "namespace": "sock-shop",
                    "label_selector": "app=redis",
                    "resource_type": "statefulset"
                },
                "parameters": {
                    "duration": "60s",
                    "intensity": 0.5,
                    "replicas_to_kill": 1
                },
                "abort_threshold": {
                    "metric": "error_rate",
                    "value": 0.05,
                    "operator": ">"
                },
                "expected_impact": "Redis failover should complete within 30s",
                "risk_level": "medium",
                "chaos_engine": "litmuschaos"
            }
        ])
        
        mock_openai.return_value.chat.completions.create.return_value = mock_response
        
        # Mock topology
        topology = {
            "services": [
                {
                    "id": "sock-shop/redis",
                    "name": "redis",
                    "namespace": "sock-shop",
                    "type": "statefulset",
                    "env": "k8s"
                }
            ]
        }
        
        # Test experiment design
        designer = ExperimentDesigner()
        experiments = designer.design(topology, count=1)
        
        assert len(experiments) == 1
        assert experiments[0]['title'] == "Redis Pod Kill"
        assert experiments[0]['action'] == "pod-kill"
        assert experiments[0]['env'] == "k8s"


class TestExecutorAdapter:
    """Test executor adapter functionality"""
    
    def test_spec_validation(self):
        """Test experiment specification validation"""
        adapter = ExecutorAdapter()
        
        # Valid spec
        valid_spec = {
            "title": "Redis Pod Kill",
            "action": "pod-kill",
            "target_selector": {
                "namespace": "sock-shop",
                "label_selector": "app=redis"
            },
            "parameters": {
                "duration": "60s"
            }
        }
        
        # Should not raise exception
        adapter._validate_spec(valid_spec)
    
    def test_spec_validation_invalid(self):
        """Test invalid specification validation"""
        adapter = ExecutorAdapter()
        
        # Invalid spec (missing required fields)
        invalid_spec = {
            "title": "Redis Pod Kill"
            # Missing action, target_selector, parameters
        }
        
        with pytest.raises(ValueError, match="Missing required field"):
            adapter._validate_spec(invalid_spec)
    
    def test_chaos_engine_generation(self):
        """Test ChaosEngine manifest generation"""
        adapter = ExecutorAdapter()
        
        spec = {
            "title": "Redis Pod Kill",
            "action": "pod-kill",
            "target_selector": {
                "namespace": "sock-shop",
                "label_selector": "app=redis",
                "resource_type": "statefulset"
            },
            "parameters": {
                "duration": "60s",
                "intensity": 0.5
            }
        }
        
        run_id = "test-run-123"
        chaos_engine = adapter._convert_to_chaos_engine(spec, run_id)
        
        assert chaos_engine["apiVersion"] == "litmuschaos.io/v1alpha1"
        assert chaos_engine["kind"] == "ChaosEngine"
        assert chaos_engine["metadata"]["name"] == f"{run_id}-pod-kill"
        assert chaos_engine["metadata"]["namespace"] == "sock-shop"
        assert chaos_engine["spec"]["appinfo"]["appns"] == "sock-shop"
        assert chaos_engine["spec"]["appinfo"]["applabel"] == "app=redis"
        
        # Check experiment configuration
        experiments = chaos_engine["spec"]["experiments"]
        assert len(experiments) == 1
        assert experiments[0]["name"] == "pod-delete"
        
        # Check environment variables
        env_vars = experiments[0]["spec"]["components"]["env"]
        duration_var = next((env for env in env_vars if env["name"] == "TOTAL_CHAOS_DURATION"), None)
        assert duration_var is not None
        assert duration_var["value"] == "60"
    
    def test_unsupported_action(self):
        """Test unsupported chaos action"""
        adapter = ExecutorAdapter()
        
        spec = {
            "title": "Invalid Action",
            "action": "unsupported-action",
            "target_selector": {
                "namespace": "default"
            },
            "parameters": {
                "duration": "60s"
            }
        }
        
        run_id = "test-run-123"
        with pytest.raises(ValueError, match="Unsupported chaos action"):
            adapter._convert_to_chaos_engine(spec, run_id)


class TestPostRunNarrator:
    """Test post-run narrator functionality"""
    
    def test_report_generation(self):
        """Test basic report generation"""
        narrator = PostRunNarrator()
        
        run_id = "test-run-123"
        spec = {
            "title": "Redis Pod Kill",
            "action": "pod-kill",
            "target_selector": {
                "namespace": "sock-shop",
                "label_selector": "app=redis"
            },
            "parameters": {
                "duration": "60s"
            }
        }
        
        monitoring_data = {
            "status": "completed",
            "duration_seconds": 60,
            "final_metrics": {
                "error_rate": 0.02,
                "latency_p95": 0.150
            },
            "impact_analysis": {
                "error_rate_impact_percent": 15.0,
                "latency_impact_percent": 25.0
            }
        }
        
        # Test report generation
        report_path = narrator.generate_report(run_id, spec, monitoring_data)
        
        assert report_path.exists()
        assert report_path.suffix == ".md"
        
        # Check report content
        content = report_path.read_text()
        assert "Redis Pod Kill" in content
        assert "test-run-123" in content
        assert "completed" in content
        
        # Cleanup
        report_path.unlink()
    
    def test_mermaid_diagram_generation(self):
        """Test Mermaid diagram generation"""
        narrator = PostRunNarrator()
        
        report_data = {
            "experiment": {
                "title": "Redis Pod Kill",
                "action": "pod-kill",
                "target_selector": {
                    "namespace": "sock-shop",
                    "label_selector": "app=redis"
                }
            }
        }
        
        diagram = narrator._generate_mermaid_diagram(report_data)
        
        assert "sequenceDiagram" in diagram
        assert "Redis Pod Kill" not in diagram  # Title should not be in diagram
        assert "pod-kill" in diagram
        assert "Execute pod-kill" in diagram


if __name__ == "__main__":
    pytest.main([__file__]) 