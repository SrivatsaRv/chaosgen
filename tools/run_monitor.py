"""
Run Monitor Tool

Monitors chaos experiment execution, tracks metrics, and handles
abort conditions based on SLI thresholds.
"""

import time
import json
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
import structlog

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from prometheus_client.parser import text_string_to_metric_families

logger = structlog.get_logger()


class RunMonitor:
    """
    Monitors chaos experiment execution and metrics.
    
    Features:
    - Real-time status tracking
    - Prometheus metrics monitoring
    - Abort condition evaluation
    - Slack notifications
    """
    
    def __init__(self, prometheus_url: str = None, slack_webhook: str = None):
        self.prometheus_url = prometheus_url or "http://localhost:9090"
        self.slack_webhook = slack_webhook
        self.active_monitors = {}  # Track active monitoring sessions
        self.registry = CollectorRegistry()
        
        # Register metrics
        self.chaos_duration = Gauge('chaos_experiment_duration_seconds', 
                                   'Duration of chaos experiment', 
                                   ['run_id', 'experiment'], 
                                   registry=self.registry)
        self.chaos_status = Gauge('chaos_experiment_status', 
                                 'Status of chaos experiment (0=running, 1=completed, 2=aborted)', 
                                 ['run_id', 'experiment'], 
                                 registry=self.registry)
        
        logger.info("Run monitor initialized", prometheus_url=self.prometheus_url)
    
    def monitor(self, run_id: str, spec: Dict[str, Any], 
                duration: Optional[str] = None, 
                abort_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        Monitor a chaos experiment execution.
        
        Args:
            run_id: Unique run identifier
            spec: Experiment specification
            duration: Override duration from spec
            abort_callback: Callback function to abort experiment
            
        Returns:
            Final monitoring results
        """
        logger.info("Starting experiment monitoring", run_id=run_id, title=spec.get('title'))
        
        # Parse duration
        duration_str = duration or spec.get('parameters', {}).get('duration', '60s')
        duration_seconds = self._parse_duration(duration_str)
        
        # Get abort threshold
        abort_threshold = spec.get('abort_threshold', {})
        
        # Initialize monitoring session
        monitor_session = {
            'run_id': run_id,
            'spec': spec,
            'started_at': datetime.utcnow(),
            'duration_seconds': duration_seconds,
            'abort_threshold': abort_threshold,
            'abort_callback': abort_callback,
            'status': 'running',
            'metrics_history': [],
            'abort_reason': None
        }
        
        self.active_monitors[run_id] = monitor_session
        
        # Send initial notification
        self._send_slack_notification(run_id, "started", spec)
        
        try:
            # Monitor loop
            end_time = monitor_session['started_at'] + timedelta(seconds=duration_seconds)
            
            while datetime.utcnow() < end_time:
                # Check experiment status
                status = self._check_experiment_status(run_id, spec)
                if status in ['completed', 'aborted', 'failed']:
                    monitor_session['status'] = status
                    break
                
                # Collect metrics
                metrics = self._collect_metrics(run_id, spec)
                monitor_session['metrics_history'].append({
                    'timestamp': datetime.utcnow().isoformat(),
                    'metrics': metrics
                })
                
                # Check abort conditions
                if self._should_abort(metrics, abort_threshold):
                    logger.warning("Abort condition met", run_id=run_id, metrics=metrics)
                    monitor_session['status'] = 'aborted'
                    monitor_session['abort_reason'] = f"Threshold exceeded: {abort_threshold}"
                    
                    if abort_callback:
                        abort_callback(run_id)
                    break
                
                # Update Prometheus metrics
                self._update_prometheus_metrics(run_id, spec, metrics)
                
                # Send periodic updates
                if len(monitor_session['metrics_history']) % 10 == 0:  # Every 5 minutes
                    self._send_slack_notification(run_id, "update", spec, metrics)
                
                time.sleep(30)  # Check every 30 seconds
            
            # Final status check
            if monitor_session['status'] == 'running':
                monitor_session['status'] = 'completed'
            
            # Send final notification
            self._send_slack_notification(run_id, monitor_session['status'], spec, 
                                        monitor_session['metrics_history'][-1]['metrics'] if monitor_session['metrics_history'] else None)
            
            # Generate final report
            final_report = self._generate_final_report(monitor_session)
            
            logger.info("Experiment monitoring completed", 
                       run_id=run_id, 
                       status=monitor_session['status'],
                       duration=datetime.utcnow() - monitor_session['started_at'])
            
            return final_report
            
        except Exception as e:
            logger.error("Monitoring failed", run_id=run_id, error=str(e))
            monitor_session['status'] = 'failed'
            monitor_session['error'] = str(e)
            raise
        finally:
            # Clean up
            if run_id in self.active_monitors:
                del self.active_monitors[run_id]
    
    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string to seconds"""
        duration_str = duration_str.lower()
        
        if duration_str.endswith('s'):
            return int(duration_str[:-1])
        elif duration_str.endswith('m'):
            return int(duration_str[:-1]) * 60
        elif duration_str.endswith('h'):
            return int(duration_str[:-1]) * 3600
        else:
            return int(duration_str)
    
    def _check_experiment_status(self, run_id: str, spec: Dict[str, Any]) -> str:
        """Check the status of the chaos experiment"""
        try:
            # This would typically call the executor adapter to get status
            # For now, we'll assume it's running unless we detect completion
            return 'running'
        except Exception as e:
            logger.warning("Failed to check experiment status", run_id=run_id, error=str(e))
            return 'unknown'
    
    def _collect_metrics(self, run_id: str, spec: Dict[str, Any]) -> Dict[str, float]:
        """Collect relevant metrics for the experiment"""
        metrics = {}
        
        try:
            # Get target service information
            target_selector = spec.get('target_selector', {})
            namespace = target_selector.get('namespace', 'default')
            label_selector = target_selector.get('label_selector', '')
            
            # Query Prometheus for relevant metrics
            metrics.update(self._query_prometheus_metrics(namespace, label_selector))
            
            # Add experiment-specific metrics
            metrics['chaos_duration'] = time.time() - self.active_monitors[run_id]['started_at'].timestamp()
            
        except Exception as e:
            logger.warning("Failed to collect metrics", run_id=run_id, error=str(e))
            # Return default metrics
            metrics = {
                'error_rate': 0.0,
                'latency_p95': 0.0,
                'cpu_usage': 0.0,
                'memory_usage': 0.0,
                'chaos_duration': time.time() - self.active_monitors[run_id]['started_at'].timestamp()
            }
        
        return metrics
    
    def _query_prometheus_metrics(self, namespace: str, label_selector: str) -> Dict[str, float]:
        """Query Prometheus for relevant metrics"""
        metrics = {}
        
        try:
            # Build label filter
            label_filter = f'namespace="{namespace}"'
            if label_selector:
                # Convert label selector to Prometheus format
                for label in label_selector.split(','):
                    if '=' in label:
                        key, value = label.split('=', 1)
                        label_filter += f',{key}="{value}"'
            
            # Query error rate
            error_rate_query = f'sum(rate(http_requests_total{{status=~"5..",{label_filter}}}[5m])) / sum(rate(http_requests_total{{{label_filter}}}[5m]))'
            error_rate = self._query_prometheus(error_rate_query)
            if error_rate is not None:
                metrics['error_rate'] = error_rate
            
            # Query latency P95
            latency_query = f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{{label_filter}}}[5m])) by (le))'
            latency = self._query_prometheus(latency_query)
            if latency is not None:
                metrics['latency_p95'] = latency
            
            # Query CPU usage
            cpu_query = f'avg(rate(container_cpu_usage_seconds_total{{{label_filter}}}[5m])) * 100'
            cpu = self._query_prometheus(cpu_query)
            if cpu is not None:
                metrics['cpu_usage'] = cpu
            
            # Query memory usage
            memory_query = f'avg(container_memory_usage_bytes{{{label_filter}}}) / avg(container_spec_memory_limit_bytes{{{label_filter}}}) * 100'
            memory = self._query_prometheus(memory_query)
            if memory is not None:
                metrics['memory_usage'] = memory
            
        except Exception as e:
            logger.warning("Failed to query Prometheus", error=str(e))
        
        return metrics
    
    def _query_prometheus(self, query: str) -> Optional[float]:
        """Execute a Prometheus query"""
        try:
            response = requests.get(
                f"{self.prometheus_url}/api/v1/query",
                params={'query': query},
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            if data['status'] == 'success' and data['data']['result']:
                return float(data['data']['result'][0]['value'][1])
            
            return None
            
        except Exception as e:
            logger.warning("Prometheus query failed", query=query, error=str(e))
            return None
    
    def _should_abort(self, metrics: Dict[str, float], threshold: Dict[str, Any]) -> bool:
        """Check if experiment should be aborted based on metrics"""
        if not threshold:
            return False
        
        metric_name = threshold.get('metric')
        threshold_value = threshold.get('value')
        operator = threshold.get('operator', '>')
        
        if metric_name not in metrics:
            return False
        
        current_value = metrics[metric_name]
        
        if operator == '>':
            return current_value > threshold_value
        elif operator == '>=':
            return current_value >= threshold_value
        elif operator == '<':
            return current_value < threshold_value
        elif operator == '<=':
            return current_value <= threshold_value
        else:
            return False
    
    def _update_prometheus_metrics(self, run_id: str, spec: Dict[str, Any], metrics: Dict[str, float]):
        """Update Prometheus metrics for the experiment"""
        try:
            experiment_name = spec.get('title', 'unknown')
            
            # Update duration metric
            self.chaos_duration.labels(run_id=run_id, experiment=experiment_name).set(
                metrics.get('chaos_duration', 0)
            )
            
            # Update status metric
            status_value = 0  # running
            if self.active_monitors[run_id]['status'] == 'completed':
                status_value = 1
            elif self.active_monitors[run_id]['status'] == 'aborted':
                status_value = 2
            
            self.chaos_status.labels(run_id=run_id, experiment=experiment_name).set(status_value)
            
        except Exception as e:
            logger.warning("Failed to update Prometheus metrics", error=str(e))
    
    def _send_slack_notification(self, run_id: str, status: str, spec: Dict[str, Any], 
                                metrics: Optional[Dict[str, float]] = None):
        """Send Slack notification about experiment status"""
        if not self.slack_webhook:
            return
        
        try:
            title = spec.get('title', 'Unknown Experiment')
            action = spec.get('action', 'unknown')
            
            if status == 'started':
                message = f"🚀 Chaos experiment started: *{title}* ({action})"
                color = "#36a64f"
            elif status == 'update':
                if metrics:
                    error_rate = metrics.get('error_rate', 0) * 100
                    latency = metrics.get('latency_p95', 0) * 1000
                    message = f"📊 Experiment update: *{title}* - Error rate: {error_rate:.1f}%, Latency: {latency:.0f}ms"
                else:
                    message = f"📊 Experiment update: *{title}* - Running..."
                color = "#ffa500"
            elif status == 'completed':
                message = f"✅ Chaos experiment completed: *{title}*"
                color = "#36a64f"
            elif status == 'aborted':
                message = f"🛑 Chaos experiment aborted: *{title}*"
                color = "#ff0000"
            else:
                message = f"❓ Chaos experiment {status}: *{title}*"
                color = "#808080"
            
            payload = {
                "attachments": [{
                    "color": color,
                    "title": "Chaos Engineering Update",
                    "text": message,
                    "fields": [
                        {
                            "title": "Run ID",
                            "value": run_id,
                            "short": True
                        },
                        {
                            "title": "Action",
                            "value": action,
                            "short": True
                        }
                    ],
                    "footer": "Chaos Advisor Agent",
                    "ts": int(time.time())
                }]
            }
            
            response = requests.post(self.slack_webhook, json=payload, timeout=10)
            response.raise_for_status()
            
        except Exception as e:
            logger.warning("Failed to send Slack notification", error=str(e))
    
    def _generate_final_report(self, monitor_session: Dict[str, Any]) -> Dict[str, Any]:
        """Generate final monitoring report"""
        duration = datetime.utcnow() - monitor_session['started_at']
        
        # Calculate metric summaries
        metrics_history = monitor_session['metrics_history']
        if metrics_history:
            latest_metrics = metrics_history[-1]['metrics']
            
            # Calculate baseline (first 30 seconds)
            baseline_metrics = []
            for entry in metrics_history[:2]:  # First 2 entries (60 seconds)
                baseline_metrics.append(entry['metrics'])
            
            if baseline_metrics:
                baseline_error_rate = sum(m.get('error_rate', 0) for m in baseline_metrics) / len(baseline_metrics)
                baseline_latency = sum(m.get('latency_p95', 0) for m in baseline_metrics) / len(baseline_metrics)
            else:
                baseline_error_rate = 0
                baseline_latency = 0
            
            # Calculate impact
            final_error_rate = latest_metrics.get('error_rate', 0)
            final_latency = latest_metrics.get('latency_p95', 0)
            
            error_rate_impact = ((final_error_rate - baseline_error_rate) / baseline_error_rate * 100) if baseline_error_rate > 0 else 0
            latency_impact = ((final_latency - baseline_latency) / baseline_latency * 100) if baseline_latency > 0 else 0
        else:
            error_rate_impact = 0
            latency_impact = 0
            latest_metrics = {}
        
        return {
            'run_id': monitor_session['run_id'],
            'status': monitor_session['status'],
            'started_at': monitor_session['started_at'].isoformat(),
            'duration_seconds': duration.total_seconds(),
            'abort_reason': monitor_session.get('abort_reason'),
            'final_metrics': latest_metrics,
            'impact_analysis': {
                'error_rate_impact_percent': error_rate_impact,
                'latency_impact_percent': latency_impact
            },
            'metrics_history': monitor_session['metrics_history'],
            'spec': monitor_session['spec']
        }
    
    def get_status(self, run_id: str) -> Dict[str, Any]:
        """Get current status of a monitored run"""
        if run_id not in self.active_monitors:
            return {'status': 'not_found'}
        
        monitor_session = self.active_monitors[run_id]
        duration = datetime.utcnow() - monitor_session['started_at']
        
        return {
            'run_id': run_id,
            'status': monitor_session['status'],
            'started_at': monitor_session['started_at'].isoformat(),
            'duration_seconds': duration.total_seconds(),
            'spec': monitor_session['spec'],
            'latest_metrics': monitor_session['metrics_history'][-1]['metrics'] if monitor_session['metrics_history'] else None
        }
    
    def list_active_monitors(self) -> List[Dict[str, Any]]:
        """List all active monitoring sessions"""
        return [
            {
                'run_id': run_id,
                'title': session['spec'].get('title'),
                'status': session['status'],
                'started_at': session['started_at'].isoformat(),
                'duration_seconds': (datetime.utcnow() - session['started_at']).total_seconds()
            }
            for run_id, session in self.active_monitors.items()
        ] 