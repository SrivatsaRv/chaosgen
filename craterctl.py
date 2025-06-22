#!/usr/bin/env python3
"""
Chaos Advisor Agent CLI

A multi-platform chaos engineering advisor that uses AI to generate,
execute, and analyze chaos experiments.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional

import click
import structlog
from dotenv import load_dotenv

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from tools.inventory_fetch import InventoryFetchTool
from tools.experiment_designer import ExperimentDesigner
from tools.executor_adapter import ExecutorAdapter
from tools.run_monitor import RunMonitor
from tools.post_run_narrator import PostRunNarrator

# Load environment variables
load_dotenv()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--config', '-c', default='stack.yaml', help='Path to stack configuration file')
@click.pass_context
def cli(ctx, verbose: bool, config: str):
    """Chaos Advisor Agent - AI-powered chaos engineering across platforms"""
    ctx.ensure_object(dict)
    ctx.obj['config'] = config
    
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate OpenAI API key
    if not os.getenv('OPENAI_API_KEY'):
        click.echo("❌ OPENAI_API_KEY environment variable is required", err=True)
        sys.exit(1)


@cli.command()
@click.option('--count', '-n', default=3, help='Number of experiments to suggest')
@click.option('--output', '-o', default='experiments/', help='Output directory for experiment specs')
@click.option('--dry-run', is_flag=True, help='Generate specs without executing')
@click.pass_context
def suggest(ctx, count: int, output: str, dry_run: bool):
    """Generate chaos experiment suggestions based on current infrastructure"""
    config_path = ctx.obj['config']
    
    try:
        logger.info("Starting experiment suggestion", count=count, config=config_path)
        
        # Step 1: Fetch inventory
        inventory_tool = InventoryFetchTool()
        topology = inventory_tool.run(Path(config_path))
        logger.info("Inventory fetched", services_count=len(topology.get('services', [])))
        
        # Step 2: Design experiments
        designer = ExperimentDesigner()
        experiments = designer.design(topology, count=count)
        logger.info("Experiments designed", experiment_count=len(experiments))
        
        # Step 3: Save experiments
        output_path = Path(output)
        output_path.mkdir(parents=True, exist_ok=True)
        
        for i, experiment in enumerate(experiments):
            filename = f"{experiment['title'].lower().replace(' ', '_')}.json"
            filepath = output_path / filename
            
            with open(filepath, 'w') as f:
                json.dump(experiment, f, indent=2)
            
            click.echo(f"📋 Experiment {i+1}: {experiment['title']}")
            click.echo(f"   Environment: {experiment['env']}")
            click.echo(f"   Action: {experiment['action']}")
            click.echo(f"   Duration: {experiment['duration']}")
            click.echo(f"   Saved to: {filepath}")
            click.echo()
        
        click.echo(f"✅ Generated {len(experiments)} experiment suggestions")
        
        if not dry_run:
            # Post to Slack if configured
            if os.getenv('SLACK_BOT_TOKEN'):
                from slackbot.app import post_experiment_suggestions
                post_experiment_suggestions(experiments)
                click.echo("📱 Posted suggestions to Slack")
        
    except Exception as e:
        logger.error("Failed to generate suggestions", error=str(e))
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('spec_file', type=click.Path(exists=True))
@click.option('--dry-run', is_flag=True, help='Validate spec without executing')
@click.option('--monitor', is_flag=True, default=True, help='Monitor execution and generate RCA')
@click.pass_context
def run(ctx, spec_file: str, dry_run: bool, monitor: bool):
    """Execute a chaos experiment from specification file"""
    try:
        logger.info("Starting experiment execution", spec_file=spec_file, dry_run=dry_run)
        
        # Load experiment spec
        with open(spec_file, 'r') as f:
            spec = json.load(f)
        
        click.echo(f"🚀 Executing: {spec['title']}")
        click.echo(f"   Environment: {spec['env']}")
        click.echo(f"   Action: {spec['action']}")
        click.echo(f"   Duration: {spec['duration']}")
        
        # Execute experiment
        adapter = ExecutorAdapter()
        run_id = adapter.apply(spec, dry_run=dry_run)
        
        if dry_run:
            click.echo("✅ Dry run completed - spec is valid")
            return
        
        click.echo(f"✅ Experiment started with run ID: {run_id}")
        
        if monitor:
            # Monitor execution
            monitor_tool = RunMonitor()
            monitor_tool.monitor(run_id, spec)
            
            # Generate RCA
            narrator = PostRunNarrator()
            report_path = narrator.generate_report(run_id, spec)
            click.echo(f"📊 RCA generated: {report_path}")
        
    except Exception as e:
        logger.error("Failed to execute experiment", error=str(e))
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('run_id')
@click.pass_context
def status(ctx, run_id: str):
    """Check status of a running experiment"""
    try:
        monitor = RunMonitor()
        status_info = monitor.get_status(run_id)
        
        click.echo(f"📊 Run ID: {run_id}")
        click.echo(f"   Status: {status_info['status']}")
        click.echo(f"   Started: {status_info['started_at']}")
        
        if status_info.get('metrics'):
            click.echo("   Current Metrics:")
            for metric, value in status_info['metrics'].items():
                click.echo(f"     {metric}: {value}")
        
        if status_info.get('slack_url'):
            click.echo(f"   Slack Updates: {status_info['slack_url']}")
        
    except Exception as e:
        logger.error("Failed to get status", error=str(e))
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--config', '-c', default='stack.yaml', help='Path to stack configuration file')
@click.pass_context
def inventory(ctx, config: str):
    """Show current infrastructure inventory"""
    try:
        inventory_tool = InventoryFetchTool()
        topology = inventory_tool.run(Path(config))
        
        click.echo("🏗️  Infrastructure Inventory")
        click.echo("=" * 50)
        
        services = topology.get('services', [])
        by_env = {}
        
        for service in services:
            env = service['env']
            if env not in by_env:
                by_env[env] = []
            by_env[env].append(service)
        
        for env, env_services in by_env.items():
            click.echo(f"\n📦 {env.upper()} ({len(env_services)} services)")
            for service in env_services:
                click.echo(f"   • {service['id']}")
                if service.get('namespace'):
                    click.echo(f"     Namespace: {service['namespace']}")
                if service.get('tags'):
                    click.echo(f"     Tags: {', '.join(service['tags'])}")
        
        click.echo(f"\n✅ Total services: {len(services)}")
        
    except Exception as e:
        logger.error("Failed to fetch inventory", error=str(e))
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('run_id')
@click.pass_context
def abort(ctx, run_id: str):
    """Abort a running experiment"""
    try:
        adapter = ExecutorAdapter()
        adapter.abort(run_id)
        click.echo(f"🛑 Aborted experiment: {run_id}")
        
    except Exception as e:
        logger.error("Failed to abort experiment", error=str(e))
        click.echo(f"❌ Error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    cli() 