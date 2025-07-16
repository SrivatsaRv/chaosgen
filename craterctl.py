#!/usr/bin/env python3
"""
ChaosGen CLI - AI-Powered Chaos Engineering

A multi-platform chaos engineering advisor that uses AI to generate,
execute, and analyze chaos experiments for microservices applications.
"""

import os
import sys
import json
import logging
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

import click
import structlog
from dotenv import load_dotenv

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from tools.inventory_fetch import InventoryFetchTool, InventoryFetchError
from tools.experiment_designer import ExperimentDesigner

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
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Version information
__version__ = "1.0.0"
__author__ = "ChaosGen Team"
__description__ = "AI-powered chaos engineering for microservices"


def print_status(message: str, status: str = "info"):
    """Print status with emoji indicators"""
    emojis = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "running": "🔄",
        "ai": "🤖",
        "chaos": "🎯",
    }
    click.echo(f"{emojis.get(status, 'ℹ️')} {message}")


def print_banner():
    """Print CRATER banner with colors"""
    banner = r"""
 ██████╗██████╗  █████╗ ████████╗███████╗██████╗ 
██╔════╝██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗
██║     ██████╔╝███████║   ██║   █████╗  ██████╔╝
██║     ██╔══██╗██╔══██║   ██║   ██╔══╝  ██╔══██╗
╚██████╗██║  ██║██║  ██║   ██║   ███████╗██║  ██║
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
                                                 
    """
    # ANSI color codes
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    print(f"{CYAN}{banner}{RESET}")
    print(f"{MAGENTA}AI-powered Chaos Engineering for Microservices{RESET}")
    print(f"{YELLOW}https://github.com/one2n/chaosgen{RESET}\n")


def validate_config(config_path: Path) -> bool:
    """Validate stack configuration file"""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "r") as f:
            yaml.safe_load(f)
        return True
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}")


def validate_experiment_spec(spec: Dict[str, Any]) -> bool:
    """Validate experiment specification"""
    required_fields = ["title", "env", "action", "duration"]
    for field in required_fields:
        if field not in spec:
            raise ValueError(f"Missing required field: {field}")

    # Validate duration format
    if not isinstance(spec["duration"], (str, int)):
        raise ValueError("Duration must be a string or integer")

    return True


def check_kubectl_config():
    """Check kubectl configuration and provide helpful suggestions if issues found"""
    import subprocess
    import re

    try:
        # Check if kubectl is available
        result = subprocess.run(
            ["kubectl", "version", "--client"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            print_status("kubectl is not available in PATH", "error")
            print_status("Please install kubectl: brew install kubectl", "info")
            return False

        # Check current context
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            print_status("No kubectl context is set", "error")
            print_status("Please configure kubectl for your cluster", "info")
            return False

        current_context = result.stdout.strip()
        print_status(f"Current kubectl context: {current_context}", "info")

        # Test cluster connection
        result = subprocess.run(
            ["kubectl", "cluster-info"], capture_output=True, text=True, timeout=15
        )

        if result.returncode != 0:
            error_output = result.stderr.strip()

            # Check for specific error patterns
            if (
                "Failed to resolve" in error_output
                or "nodename nor servname provided" in error_output
                or "no such host" in error_output
            ):
                print_status(
                    "❌ Cluster connection failed: DNS resolution error", "error"
                )
                print_status(
                    "Your kubectl configuration appears to be outdated", "warning"
                )
                print()
                print_status("Hint: Update your kubectl context with:", "info")
                print_status(
                    "  aws eks update-kubeconfig --region us-east-2 --name sock-shop",
                    "info",
                )
                print()
                return False

            elif "connection refused" in error_output or "timeout" in error_output:
                print_status("❌ Cluster connection failed: Network timeout", "error")
                print_status(
                    "The cluster may be down or network connectivity issues", "warning"
                )
                print_status("Check if your cluster is running and accessible", "info")
                return False

            elif "unauthorized" in error_output or "forbidden" in error_output:
                print_status(
                    "❌ Cluster connection failed: Authentication error", "error"
                )
                print_status(
                    "Your credentials may have expired or lack permissions", "warning"
                )
                print_status(
                    "Try updating your kubeconfig or checking IAM permissions", "info"
                )
                return False

            else:
                print_status(f"❌ Cluster connection failed: {error_output}", "error")
                print_status("Hint: Update your kubectl context with:", "info")
                print_status(
                    "  aws eks update-kubeconfig --region us-east-2 --name sock-shop",
                    "info",
                )
                print()
                return False

        print_status(
            "✅ kubectl configuration is valid and cluster is accessible", "success"
        )
        return True

    except subprocess.TimeoutExpired:
        print_status("❌ kubectl command timed out", "error")
        print_status("Check your network connectivity to the cluster", "info")
        return False
    except FileNotFoundError:
        print_status("❌ kubectl is not installed", "error")
        print_status("Please install kubectl: brew install kubectl", "info")
        return False
    except Exception as e:
        print_status(f"❌ Unexpected error checking kubectl config: {str(e)}", "error")
        print_status("Hint: Update your kubectl context with:", "info")
        print_status(
            "  aws eks update-kubeconfig --region us-east-2 --name sock-shop", "info"
        )
        print()
        return False


class BannerGroup(click.Group):
    def get_help(self, ctx):
        print_banner()
        return super().get_help(ctx)

    def invoke(self, ctx):
        # Show banner only for: no subcommand, help, version, or demo
        show_banner = False
        if not ctx.invoked_subcommand:
            show_banner = True
        elif ctx.invoked_subcommand in ["version", "demo"]:
            show_banner = True
        # Also show for --help/-h
        if any(arg in sys.argv for arg in ["--help", "-h"]):
            show_banner = True
        if show_banner:
            print_banner()
        return super().invoke(ctx)


@click.group(cls=BannerGroup)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx, verbose: bool):
    """ChaosGen - AI-powered chaos experiment generation

    ChaosGen helps you generate context-aware chaos experiments for your
    microservices using AI. It discovers your infrastructure and creates
    experiments in a deterministic JSON format.

    Examples:
        craterctl inventory                    # Show infrastructure
        craterctl suggest --count 5           # Generate 5 experiments
        craterctl suggest --output ./my-experiments/  # Custom output
    """
    ctx.ensure_object(dict)

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


@cli.command()
@click.option("--count", "-n", default=3, help="Number of experiments to suggest")
@click.option(
    "--output",
    "-o",
    default="experiments/",
    help="Output directory for experiment specs",
)
@click.option("--dry-run", is_flag=True, help="Generate specs without executing")
@click.option("--config", "-c", default="stack.yaml", help="Path to stack configuration file")
@click.pass_context
def suggest(ctx, count: int, output: str, dry_run: bool, config: str):
    """Generate chaos experiment suggestions based on current infrastructure

    Uses AI to analyze your infrastructure and generate context-aware chaos
    experiments that will help you identify potential weaknesses.

    Examples:
        craterctl suggest                    # Generate 3 experiments
        craterctl suggest --count 5         # Generate 5 experiments
        craterctl suggest --dry-run         # Validate without executing
        craterctl suggest --output ./my-experiments/  # Custom output dir
    """

    # Check if we have any LLM provider configured
    mock_mode = os.getenv("CHAOSGEN_MOCK_MODE", "false").lower() == "true"
    has_openai = os.getenv("OPENAI_API_KEY") is not None
    has_gemini = os.getenv("GOOGLE_API_KEY") is not None

    if not mock_mode and not has_openai and not has_gemini:
        print_status("No LLM API key found for experiment generation", "error")
        print_status("💡 Available options:", "info")
        print_status("   1. Set OpenAI key: export OPENAI_API_KEY='your-key'", "info")
        print_status("   2. Set Gemini key: export GOOGLE_API_KEY='your-key'", "info")
        print_status("   3. Use mock mode: export CHAOSGEN_MOCK_MODE=true", "info")
        sys.exit(1)

    try:
        print_status("Starting AI-powered experiment generation", "ai")
        logger.info("Starting experiment suggestion", count=count, config=config)

        # Check kubectl configuration first
        print_status("Checking kubectl configuration...", "info")
        if not check_kubectl_config():
            print_status("Please fix kubectl configuration and try again", "error")
            sys.exit(1)

        # Step 1: Fetch inventory
        print_status("Discovering infrastructure...", "info")
        inventory_tool = InventoryFetchTool()
        topology = inventory_tool.run(Path(config))
        services_count = len(topology.get("services", []))
        print_status(f"Found {services_count} services", "success")
        logger.info("Inventory fetched", services_count=services_count)

        # Step 2: Design experiments with AI
        print_status(
            "AI is analyzing your infrastructure and generating experiments...", "ai"
        )
        designer = ExperimentDesigner()
        experiments = designer.design(topology, count=count)
        print_status(
            f"AI generated {len(experiments)} context-aware experiments", "success"
        )
        logger.info("Experiments designed", experiment_count=len(experiments))

        # Step 3: Save experiments to files
        if not dry_run:
            print_status("Saving experiments to files...", "info")
            saved_files = designer.save_experiments(experiments, Path(output))

            print_status(f"✅ Generated {len(experiments)} experiment suggestions")
            print_status(f"📁 Saved to: {output}")

            for i, (exp, filepath) in enumerate(zip(experiments, saved_files)):
                print_status(f"📋 Experiment {i+1}: {exp['title']}")
                print_status(f"   Description: {exp['description']}")
                print_status(f"   Action: {exp['action']} • Risk: {exp['risk_level']}")
                print_status(f"   Saved to: {filepath}")
                print()
        else:
            print_status(
                f"✅ Generated {len(experiments)} experiment suggestions (dry-run)"
            )
            for i, exp in enumerate(experiments):
                print_status(f"📋 Experiment {i+1}: {exp['title']}")
                print_status(f"   Description: {exp['description']}")
                print_status(f"   Action: {exp['action']} • Risk: {exp['risk_level']}")
                print()

    except Exception as e:
        logger.error("Failed to generate suggestions", error=str(e))
        print_status(f"Failed to generate suggestions: {e}", "error")
        sys.exit(1)


@cli.command(name="inventory")
@click.pass_context
def inventory(ctx):
    """Show current infrastructure inventory (alias: ls)

    Discovers and displays all services in your infrastructure that can be
    targeted for chaos experiments.

    Examples:
        craterctl inventory              # Show all services
        craterctl ls                     # Short alias
        craterctl inventory --config custom.yaml  # Custom config
    """
    try:
        # Check kubectl configuration first
        print_status("Checking kubectl configuration...", "info")
        if not check_kubectl_config():
            print_status("Please fix kubectl configuration and try again", "error")
            sys.exit(1)

        print_status("Discovering infrastructure...", "info")
        inventory_tool = InventoryFetchTool()
        topology = inventory_tool.run(Path(config))

        # The inventory tool now handles its own output
        # Just return success status
        print_status("Infrastructure discovery completed", "success")

    except InventoryFetchError as e:
        print_status("Infrastructure discovery failed", "error")
        click.echo(f"\n❌ Error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error during inventory fetch", error=str(e))
        print_status("Unexpected error during infrastructure discovery", "error")
        click.echo(f"\n❌ Unexpected error: {str(e)}")
        sys.exit(1)


@cli.command(name="ls")
@click.option(
    "--config", "-c", default="stack.yaml", help="Path to stack configuration file"
)
@click.pass_context
def ls(ctx, config: str):
    """Short alias for inventory command"""
    # Call the inventory function with the same logic
    try:
        # Check kubectl configuration first
        print_status("Checking kubectl configuration...", "info")
        if not check_kubectl_config():
            print_status("Please fix kubectl configuration and try again", "error")
            sys.exit(1)

        print_status("Discovering infrastructure...", "info")
        inventory_tool = InventoryFetchTool()
        topology = inventory_tool.run(Path(config))

        # The inventory tool now handles its own output
        # Just return success status
        print_status("Infrastructure discovery completed", "success")

    except InventoryFetchError as e:
        print_status("Infrastructure discovery failed", "error")
        click.echo(f"\n❌ Error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error("Unexpected error during inventory fetch", error=str(e))
        print_status("Unexpected error during infrastructure discovery", "error")
        click.echo(f"\n❌ Unexpected error: {str(e)}")
        sys.exit(1)


@cli.command()
def version():
    """Show version information"""
    click.echo(f"ChaosGen v{__version__}")
    click.echo(f"{__description__}")
    click.echo(f"Author: {__author__}")
    click.echo()
    click.echo("Built with:")
    click.echo("  🤖 AI-powered experiment design")
    click.echo("  🎯 Context-aware chaos engineering")
    click.echo("  📊 Deterministic JSON format")
    click.echo("  🔒 Safety-first approach")


@cli.command()
def check():
    """Check kubectl configuration and cluster connectivity

    Validates your kubectl setup and provides helpful suggestions
    if there are any configuration issues.

    Examples:
        craterctl check              # Check kubectl configuration
    """
    print_status("Checking kubectl configuration and cluster connectivity...", "info")

    if check_kubectl_config():
        print_status(
            "✅ All checks passed! You're ready to run chaos experiments", "success"
        )
    else:
        print_status(
            "❌ Configuration issues found. Please fix them and try again", "error"
        )
        sys.exit(1)


@cli.command()
def check_llm():
    """Check LLM configuration and availability

    Validates your LLM API keys and shows which provider will be used.

    Examples:
        craterctl check-llm          # Check LLM configuration
    """
    print_status("Checking LLM configuration and availability...", "info")

    try:
        from tools.llm_adapter import get_llm_adapter

        adapter = get_llm_adapter()

        # Get environment detection info
        env_info = adapter.detect_environment()

        print_status("Environment Variables:", "info")
        print(f"  CHAOSGEN_LLM_PROVIDER: {env_info['provider_override'] or 'Not set'}")
        print(
            f"  OPENAI_API_KEY: {'✅ Set' if env_info['openai_key_set'] else '❌ Not set'}"
        )
        print(
            f"  GOOGLE_API_KEY: {'✅ Set' if env_info['gemini_key_set'] else '❌ Not set'}"
        )
        print(
            f"  CHAOSGEN_MOCK_MODE: {'✅ Enabled' if env_info['mock_mode_set'] else '❌ Disabled'}"
        )
        print(f"  CHAOSGEN_LLM_MODEL: {env_info['current_model']}")

        print_status("Library Availability:", "info")
        print(
            f"  OpenAI Library: {'✅ Installed' if env_info['openai_library_available'] else '❌ Not installed'}"
        )
        print(
            f"  Gemini Library: {'✅ Installed' if env_info['gemini_library_available'] else '❌ Not installed'}"
        )

        print_status("Detection Results:", "info")
        print(f"  Detected Provider: {env_info['detected_provider']}")
        print(f"  Selected Model: {env_info['selected_model']}")

        if env_info["fallback_reason"]:
            print(f"  Fallback Reason: {env_info['fallback_reason']}")

        # Check availability
        availability = adapter.check_availability()
        if availability["available"]:
            print_status(f"✅ {availability['message']}", "success")
        else:
            print_status(f"❌ {availability['error']}", "error")

        # Provide helpful suggestions
        print_status("Configuration Suggestions:", "info")
        if env_info["provider_override"] == "gemini":
            if not env_info["gemini_key_set"]:
                print("  💡 To use Gemini: export GOOGLE_API_KEY='your-key'")
            if not env_info["gemini_library_available"]:
                print("  💡 Install Gemini library: pip install google-generativeai")
        elif env_info["provider_override"] == "openai":
            if not env_info["openai_key_set"]:
                print("  💡 To use OpenAI: export OPENAI_API_KEY='your-key'")
            if not env_info["openai_library_available"]:
                print("  💡 Install OpenAI library: pip install openai")
        elif not env_info["openai_key_set"] and not env_info["gemini_key_set"]:
            print("  💡 To use OpenAI: export OPENAI_API_KEY='your-key'")
            print("  💡 To use Gemini: export GOOGLE_API_KEY='your-key'")
            print("  💡 To use mock mode: export CHAOSGEN_MOCK_MODE=true")
        elif env_info["gemini_key_set"] and not env_info["gemini_library_available"]:
            print("  💡 Install Gemini library: pip install google-generativeai")
        elif env_info["openai_key_set"] and not env_info["openai_library_available"]:
            print("  💡 Install OpenAI library: pip install openai")

        print_status("✅ LLM configuration check completed", "success")
    except Exception as e:
        print_status(f"❌ LLM configuration check failed: {e}", "error")
        sys.exit(1)


@cli.command()
@click.option("--region", "-r", help="AWS region to search for clusters")
@click.option("--cluster-name", "-c", help="Specific cluster name to configure")
def configure(region: str, cluster_name: str):
    """Discover and configure kubectl for AWS EKS clusters

    Lists available EKS clusters and helps you configure kubectl
    for the selected cluster.

    Examples:
        craterctl configure                    # Interactive cluster selection
        craterctl configure --region us-east-2 # List clusters in specific region
        craterctl configure --cluster-name sock-shop # Configure specific cluster
    """
    import subprocess
    import json

    try:
        # Check if AWS CLI is configured
        print_status("Checking AWS CLI configuration...", "info")
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            print_status(
                "❌ AWS CLI is not configured or credentials are invalid", "error"
            )
            print_status("Please configure AWS CLI first:", "info")
            print_status("   aws configure", "info")
            sys.exit(1)

        identity = json.loads(result.stdout)
        print_status(
            f"✅ AWS CLI configured for: {identity.get('Account', 'Unknown')}",
            "success",
        )

        # Determine region
        if not region:
            # Try to get default region
            result = subprocess.run(
                ["aws", "configure", "get", "region"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                region = result.stdout.strip()
                print_status(f"Using default region: {region}", "info")
            else:
                print_status("No default region set, using us-east-2", "warning")
                region = "us-east-2"
        else:
            print_status(f"Using specified region: {region}", "info")

        # List EKS clusters
        print_status(f"Discovering EKS clusters in {region}...", "info")
        result = subprocess.run(
            ["aws", "eks", "list-clusters", "--region", region],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            print_status(
                f"❌ Failed to list clusters in {region}: {result.stderr}", "error"
            )
            sys.exit(1)

        clusters_data = json.loads(result.stdout)
        clusters = clusters_data.get("clusters", [])

        if not clusters:
            print_status(f"❌ No EKS clusters found in {region}", "error")
            print_status("Try a different region or create a cluster first", "info")
            sys.exit(1)

        print_status(f"Found {len(clusters)} EKS cluster(s) in {region}:", "success")

        # Get detailed cluster info
        cluster_details = []
        for cluster in clusters:
            try:
                result = subprocess.run(
                    [
                        "aws",
                        "eks",
                        "describe-cluster",
                        "--region",
                        region,
                        "--name",
                        cluster,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )

                if result.returncode == 0:
                    cluster_info = json.loads(result.stdout)["cluster"]
                    cluster_details.append(
                        {
                            "name": cluster,
                            "status": cluster_info.get("status", "Unknown"),
                            "version": cluster_info.get("version", "Unknown"),
                            "endpoint": cluster_info.get("endpoint", "Unknown"),
                            "created": cluster_info.get("createdAt", "Unknown"),
                        }
                    )
                else:
                    cluster_details.append(
                        {
                            "name": cluster,
                            "status": "Error getting details",
                            "version": "Unknown",
                            "endpoint": "Unknown",
                            "created": "Unknown",
                        }
                    )
            except Exception as e:
                cluster_details.append(
                    {
                        "name": cluster,
                        "status": f"Error: {str(e)}",
                        "version": "Unknown",
                        "endpoint": "Unknown",
                        "created": "Unknown",
                    }
                )

        # Display clusters
        for i, cluster in enumerate(cluster_details, 1):
            status_emoji = "✅" if cluster["status"] == "ACTIVE" else "⚠️"
            print(f"{i}. {status_emoji} {cluster['name']}")
            print(f"   Status: {cluster['status']}")
            print(f"   Version: {cluster['version']}")
            print(f"   Created: {cluster['created']}")
            print()

        # Select cluster
        selected_cluster = None
        if cluster_name:
            # Use specified cluster name
            if cluster_name in [c["name"] for c in cluster_details]:
                selected_cluster = cluster_name
                print_status(f"Using specified cluster: {selected_cluster}", "info")
            else:
                print_status(
                    f"❌ Cluster '{cluster_name}' not found in {region}", "error"
                )
                sys.exit(1)
        else:
            # Interactive selection
            if len(clusters) == 1:
                selected_cluster = clusters[0]
                print_status(
                    f"Only one cluster found, selecting: {selected_cluster}", "info"
                )
            else:
                try:
                    choice = input(f"Select cluster (1-{len(clusters)}): ").strip()
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(clusters):
                        selected_cluster = clusters[choice_idx]
                    else:
                        print_status("❌ Invalid selection", "error")
                        sys.exit(1)
                except (ValueError, KeyboardInterrupt):
                    print_status("❌ Invalid input or cancelled", "error")
                    sys.exit(1)

        # Configure kubectl for selected cluster
        print_status(f"Configuring kubectl for cluster: {selected_cluster}", "info")
        result = subprocess.run(
            [
                "aws",
                "eks",
                "update-kubeconfig",
                "--region",
                region,
                "--name",
                selected_cluster,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print_status(
                f"✅ Successfully configured kubectl for {selected_cluster}", "success"
            )
            print_status(f"Current context: {selected_cluster}", "info")

            # Test the configuration
            print_status("Testing cluster connectivity...", "info")
            if check_kubectl_config():
                print_status(
                    "✅ Cluster is accessible and ready for chaos experiments!",
                    "success",
                )
            else:
                print_status(
                    "⚠️ Cluster configured but connectivity test failed", "warning"
                )
                print_status(
                    "You may need to check network connectivity or IAM permissions",
                    "info",
                )
        else:
            print_status(f"❌ Failed to configure kubectl: {result.stderr}", "error")
            sys.exit(1)

    except subprocess.TimeoutExpired:
        print_status("❌ Command timed out. Check your AWS CLI configuration", "error")
        sys.exit(1)
    except FileNotFoundError:
        print_status("❌ AWS CLI is not installed", "error")
        print_status("Please install AWS CLI: brew install awscli", "info")
        sys.exit(1)
    except Exception as e:
        print_status(f"❌ Unexpected error: {str(e)}", "error")
        sys.exit(1)


if __name__ == "__main__":
    cli()
