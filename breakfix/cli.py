import argparse
import asyncio

from breakfix.runner import run


def main():
    parser = argparse.ArgumentParser(
        description="Agentic TDD Foundry: Transform ideas into production-grade software"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Run command (existing behavior)
    run_parser = subparsers.add_parser("run", help="Run the pipeline directly")
    run_parser.add_argument("working_dir", help="Working directory for the project")

    # Serve command (new)
    serve_parser = subparsers.add_parser(
        "serve", help="Start deployment server (enables UI retry)"
    )
    serve_parser.add_argument(
        "--name",
        default="breakfix-deployment",
        help="Deployment name (default: breakfix-deployment)",
    )

    args = parser.parse_args()

    if args.command == "serve":
        serve(args.name)
    elif args.command == "run":
        asyncio.run(run(working_directory=args.working_dir))
    else:
        # Default: show help
        parser.print_help()


def serve(deployment_name: str):
    """Start the Prefect deployment server."""
    from breakfix.flows import breakfix_project_flow

    breakfix_project_flow.serve(
        name=deployment_name,
        tags=["breakfix"],
        description="BreakFix TDD pipeline - run from UI with working_directory parameter",
    )
