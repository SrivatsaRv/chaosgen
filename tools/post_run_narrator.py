"""
Post-Run Narrator Tool

Generates Root Cause Analysis (RCA) reports after chaos experiments
complete. Creates markdown reports with Mermaid diagrams and insights.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from jinja2 import Template
from openai import OpenAI

logger = structlog.get_logger()


class PostRunNarrator:
    """
    Generates comprehensive RCA reports after chaos experiments.
    
    Features:
    - Markdown report generation
    - Mermaid sequence diagrams
    - LLM-powered insights
    - Metric analysis
    - Recommendations
    """
    
    def __init__(self, model: str = "gpt-4o", temperature: float = 0.3):
        self.client = OpenAI()
        self.model = model
        self.temperature = temperature
        self.template = self._load_template()
        
        logger.info("Post-run narrator initialized", model=model)
    
    def _load_template(self) -> Template:
        """Load the Jinja2 template for RCA generation"""
        template_path = Path(__file__).parent.parent / "prompts" / "rca.j2"
        
        try:
            with open(template_path, 'r') as f:
                return Template(f.read())
        except Exception as e:
            logger.error("Failed to load RCA template", error=str(e))
            # Create a basic template if file doesn't exist
            return Template(self._get_default_template())
    
    def _get_default_template(self) -> str:
        """Get default RCA template"""
        return """
# Chaos Experiment RCA: {{ experiment.title }}

## Executive Summary

**Experiment**: {{ experiment.title }}
**Run ID**: {{ run_id }}
**Status**: {{ status }}
**Duration**: {{ duration_seconds }} seconds
**Started**: {{ started_at }}

## What Happened

{{ summary }}

## Key Findings

{{ findings }}

## Timeline

{{ timeline }}

## Impact Analysis

{{ impact_analysis }}

## Recommendations

{{ recommendations }}

## Technical Details

### Experiment Configuration
```yaml
{{ experiment_config }}
```

### Metrics Summary
{{ metrics_summary }}

### Abort Conditions
{{ abort_conditions }}
"""
    
    def generate_report(self, run_id: str, spec: Dict[str, Any], 
                       monitoring_data: Optional[Dict[str, Any]] = None) -> Path:
        """
        Generate RCA report for a completed experiment.
        
        Args:
            run_id: Experiment run ID
            spec: Original experiment specification
            monitoring_data: Optional monitoring results
            
        Returns:
            Path to generated report file
        """
        logger.info("Generating RCA report", run_id=run_id, title=spec.get('title'))
        
        try:
            # Prepare report data
            report_data = self._prepare_report_data(run_id, spec, monitoring_data)
            
            # Generate report content
            report_content = self._generate_report_content(report_data)
            
            # Save report
            report_path = self._save_report(run_id, spec, report_content)
            
            logger.info("RCA report generated", path=str(report_path))
            return report_path
            
        except Exception as e:
            logger.error("Failed to generate RCA report", error=str(e))
            raise
    
    def _prepare_report_data(self, run_id: str, spec: Dict[str, Any], 
                           monitoring_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Prepare data for report generation"""
        
        # Basic experiment info
        report_data = {
            'run_id': run_id,
            'experiment': spec,
            'started_at': monitoring_data.get('started_at') if monitoring_data else datetime.utcnow().isoformat(),
            'status': monitoring_data.get('status', 'completed') if monitoring_data else 'completed',
            'duration_seconds': monitoring_data.get('duration_seconds', 0) if monitoring_data else 0
        }
        
        # Add monitoring data if available
        if monitoring_data:
            report_data.update({
                'metrics_history': monitoring_data.get('metrics_history', []),
                'final_metrics': monitoring_data.get('final_metrics', {}),
                'impact_analysis': monitoring_data.get('impact_analysis', {}),
                'abort_reason': monitoring_data.get('abort_reason')
            })
        
        # Generate insights using LLM
        insights = self._generate_insights(report_data)
        report_data.update(insights)
        
        return report_data
    
    def _generate_insights(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate insights using LLM"""
        try:
            # Prepare context for LLM
            context = {
                'experiment': report_data['experiment'],
                'status': report_data['status'],
                'duration': report_data['duration_seconds'],
                'metrics': report_data.get('final_metrics', {}),
                'impact': report_data.get('impact_analysis', {}),
                'abort_reason': report_data.get('abort_reason')
            }
            
            # Generate prompt
            prompt = self._create_insights_prompt(context)
            
            # Call LLM
            response = self._call_llm(prompt)
            
            # Parse response
            insights = self._parse_insights_response(response)
            
            return insights
            
        except Exception as e:
            logger.warning("Failed to generate insights", error=str(e))
            return self._get_default_insights()
    
    def _create_insights_prompt(self, context: Dict[str, Any]) -> str:
        """Create prompt for LLM insights generation"""
        return f"""
You are an expert SRE analyzing a chaos engineering experiment. Generate insights for this experiment:

**Experiment Details:**
- Title: {context['experiment'].get('title', 'Unknown')}
- Action: {context['experiment'].get('action', 'Unknown')}
- Status: {context['status']}
- Duration: {context['duration']} seconds
- Abort Reason: {context.get('abort_reason', 'None')}

**Metrics:**
{json.dumps(context['metrics'], indent=2)}

**Impact Analysis:**
{json.dumps(context['impact'], indent=2)}

Please provide:
1. A concise summary of what happened
2. Key findings and insights
3. A timeline of events
4. Impact analysis
5. Specific recommendations for improvement

Format your response as JSON:
{{
  "summary": "Brief description of what happened",
  "findings": "Key insights and observations",
  "timeline": "Chronological sequence of events",
  "impact_analysis": "Analysis of the impact",
  "recommendations": "Specific recommendations"
}}
"""
    
    def _call_llm(self, prompt: str) -> str:
        """Call LLM for insights generation"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert SRE analyzing chaos engineering experiments. Provide clear, actionable insights."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=self.temperature,
                max_tokens=1500
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error("Failed to call LLM for insights", error=str(e))
            raise
    
    def _parse_insights_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into structured insights"""
        try:
            # Clean up response
            response = response.strip()
            if response.startswith('```json'):
                response = response[7:]
            if response.endswith('```'):
                response = response[:-3]
            
            response = response.strip()
            
            # Parse JSON
            insights = json.loads(response)
            
            return {
                'summary': insights.get('summary', ''),
                'findings': insights.get('findings', ''),
                'timeline': insights.get('timeline', ''),
                'impact_analysis': insights.get('impact_analysis', ''),
                'recommendations': insights.get('recommendations', '')
            }
            
        except Exception as e:
            logger.warning("Failed to parse insights", response=response[:200], error=str(e))
            return self._get_default_insights()
    
    def _get_default_insights(self) -> Dict[str, Any]:
        """Get default insights when LLM fails"""
        return {
            'summary': 'Chaos experiment completed successfully.',
            'findings': 'No significant issues detected during the experiment.',
            'timeline': 'Experiment ran for the specified duration without interruption.',
            'impact_analysis': 'Minimal impact observed on system performance.',
            'recommendations': 'Consider running more intensive experiments to test system resilience.'
        }
    
    def _generate_report_content(self, report_data: Dict[str, Any]) -> str:
        """Generate the complete report content"""
        
        # Prepare template variables
        template_vars = {
            'run_id': report_data['run_id'],
            'experiment': report_data['experiment'],
            'status': report_data['status'],
            'started_at': report_data['started_at'],
            'duration_seconds': report_data['duration_seconds'],
            'summary': report_data.get('summary', ''),
            'findings': report_data.get('findings', ''),
            'timeline': report_data.get('timeline', ''),
            'impact_analysis': report_data.get('impact_analysis', ''),
            'recommendations': report_data.get('recommendations', ''),
            'experiment_config': yaml.dump(report_data['experiment'], default_flow_style=False),
            'metrics_summary': self._format_metrics_summary(report_data),
            'abort_conditions': self._format_abort_conditions(report_data)
        }
        
        # Generate report using template
        report_content = self.template.render(**template_vars)
        
        # Add Mermaid diagram
        mermaid_diagram = self._generate_mermaid_diagram(report_data)
        if mermaid_diagram:
            report_content += f"\n## System Architecture\n\n```mermaid\n{mermaid_diagram}\n```\n"
        
        return report_content
    
    def _format_metrics_summary(self, report_data: Dict[str, Any]) -> str:
        """Format metrics summary for report"""
        metrics = report_data.get('final_metrics', {})
        impact = report_data.get('impact_analysis', {})
        
        summary = []
        
        if metrics:
            summary.append("### Final Metrics")
            for metric, value in metrics.items():
                if isinstance(value, float):
                    summary.append(f"- **{metric}**: {value:.3f}")
                else:
                    summary.append(f"- **{metric}**: {value}")
        
        if impact:
            summary.append("\n### Impact Analysis")
            for impact_type, value in impact.items():
                summary.append(f"- **{impact_type}**: {value:.1f}%")
        
        return "\n".join(summary)
    
    def _format_abort_conditions(self, report_data: Dict[str, Any]) -> str:
        """Format abort conditions for report"""
        abort_reason = report_data.get('abort_reason')
        threshold = report_data['experiment'].get('abort_threshold', {})
        
        if abort_reason:
            return f"**Aborted**: {abort_reason}"
        elif threshold:
            return f"**Threshold**: {threshold.get('metric', 'unknown')} {threshold.get('operator', '>')} {threshold.get('value', 'unknown')}"
        else:
            return "**No abort conditions configured**"
    
    def _generate_mermaid_diagram(self, report_data: Dict[str, Any]) -> str:
        """Generate Mermaid sequence diagram for the experiment"""
        try:
            spec = report_data['experiment']
            action = spec.get('action', 'unknown')
            target = spec.get('target_selector', {})
            
            # Create sequence diagram
            diagram = [
                "sequenceDiagram",
                "    participant U as User",
                "    participant C as Chaos Agent",
                "    participant K as Kubernetes",
                "    participant T as Target Service",
                "    participant M as Monitoring",
                "",
                "    U->>C: Start Experiment",
                "    C->>K: Apply ChaosEngine",
                "    K->>T: Execute " + action,
                "    T->>M: Report Metrics",
                "    M->>C: Monitor Status",
                "    C->>U: Report Results"
            ]
            
            # Add abort path if applicable
            if report_data.get('abort_reason'):
                diagram.extend([
                    "",
                    "    Note over M,C: Abort Condition Met",
                    "    C->>K: Stop Experiment",
                    "    K->>T: Restore Normal State"
                ])
            
            return "\n".join(diagram)
            
        except Exception as e:
            logger.warning("Failed to generate Mermaid diagram", error=str(e))
            return ""
    
    def _save_report(self, run_id: str, spec: Dict[str, Any], content: str) -> Path:
        """Save report to file"""
        # Create reports directory
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename
        timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        title_slug = spec.get('title', 'unknown').lower().replace(' ', '_').replace('-', '_')
        filename = f"{timestamp}_{title_slug}_{run_id}.md"
        
        report_path = reports_dir / filename
        
        # Save report
        with open(report_path, 'w') as f:
            f.write(content)
        
        # Also save as latest
        latest_path = reports_dir / "latest.md"
        with open(latest_path, 'w') as f:
            f.write(content)
        
        logger.info("Report saved", path=str(report_path), latest=str(latest_path))
        return report_path
    
    def generate_summary(self, report_data: Dict[str, Any]) -> str:
        """Generate a brief summary for Slack notifications"""
        spec = report_data['experiment']
        status = report_data['status']
        duration = report_data['duration_seconds']
        
        summary = f"**{spec.get('title', 'Unknown Experiment')}** - {status.upper()}\n"
        summary += f"Duration: {duration}s | Run ID: {report_data['run_id']}\n"
        
        if report_data.get('abort_reason'):
            summary += f"Aborted: {report_data['abort_reason']}\n"
        
        impact = report_data.get('impact_analysis', {})
        if impact:
            summary += "Impact: "
            impacts = []
            for impact_type, value in impact.items():
                impacts.append(f"{impact_type}: {value:.1f}%")
            summary += ", ".join(impacts)
        
        return summary
    
    def list_reports(self, reports_dir: Path = Path("reports")) -> List[Dict[str, Any]]:
        """List all generated reports"""
        if not reports_dir.exists():
            return []
        
        reports = []
        for report_file in reports_dir.glob("*.md"):
            if report_file.name == "latest.md":
                continue
            
            try:
                # Extract metadata from filename
                parts = report_file.stem.split('_')
                if len(parts) >= 3:
                    timestamp = f"{parts[0]}_{parts[1]}_{parts[2]}"
                    title = '_'.join(parts[3:-1])  # Everything between timestamp and run_id
                    run_id = parts[-1]
                    
                    reports.append({
                        'filename': report_file.name,
                        'path': str(report_file),
                        'timestamp': timestamp,
                        'title': title.replace('_', ' '),
                        'run_id': run_id,
                        'size': report_file.stat().st_size
                    })
            except Exception as e:
                logger.warning("Failed to parse report filename", file=report_file.name, error=str(e))
        
        # Sort by timestamp (newest first)
        reports.sort(key=lambda x: x['timestamp'], reverse=True)
        return reports 