"""Emet CLI — run investigations from the command line.

Usage:
    emet investigate "Acme Corp shell companies in Panama"
    emet search "John Smith" --type Person --source opensanctions
    emet workflow corporate_ownership --target "Acme Corp"
    emet serve                        # Start MCP server
    emet status                       # Show investigation summary

The duct-tape-and-spite interface to the investigation engine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="emet",
        description="Emet — Investigative Journalism Agent",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    parser.add_argument(
        "--llm", default="stub", help="LLM provider (stub, ollama, anthropic)"
    )

    subparsers = parser.add_subparsers(dest="command")

    # investigate
    inv = subparsers.add_parser("investigate", help="Run a full investigation")
    inv.add_argument("goal", help="Investigation goal (natural language)")
    inv.add_argument("--max-turns", type=int, default=15, help="Max agent turns")
    inv.add_argument("--no-sanctions", action="store_true", help="Skip auto sanctions screening")
    inv.add_argument("--no-news", action="store_true", help="Skip auto news check")
    inv.add_argument("--output", "-o", help="Save report to file")

    # search
    srch = subparsers.add_parser("search", help="Quick entity search")
    srch.add_argument("query", help="Search query")
    srch.add_argument("--type", default="Any", help="Entity type filter")
    srch.add_argument("--source", action="append", help="Data sources")
    srch.add_argument("--limit", type=int, default=20)

    # workflow
    wf = subparsers.add_parser("workflow", help="Run a predefined workflow")
    wf.add_argument("name", help="Workflow name")
    wf.add_argument("--target", required=True, help="Investigation target")
    wf.add_argument("--dry-run", action="store_true", help="Preview without executing")
    wf.add_argument("--params", type=json.loads, default={}, help="Extra params as JSON")

    # serve
    srv = subparsers.add_parser("serve", help="Start MCP server")
    srv.add_argument("--transport", default="stdio", choices=["stdio", "sse"])

    # status
    subparsers.add_parser("status", help="Show system status")

    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch
    try:
        if args.command == "investigate":
            asyncio.run(_cmd_investigate(args))
        elif args.command == "search":
            asyncio.run(_cmd_search(args))
        elif args.command == "workflow":
            asyncio.run(_cmd_workflow(args))
        elif args.command == "serve":
            _cmd_serve(args)
        elif args.command == "status":
            _cmd_status()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        logger.error("Error: %s", exc)
        if args.verbose:
            raise
        sys.exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def _cmd_investigate(args: argparse.Namespace) -> None:
    """Run a full agentic investigation."""
    from emet.agent import InvestigationAgent, AgentConfig

    config = AgentConfig(
        max_turns=args.max_turns,
        auto_sanctions_screen=not args.no_sanctions,
        auto_news_check=not args.no_news,
        llm_provider=args.llm,
        verbose=args.verbose,
    )

    agent = InvestigationAgent(config=config)
    print(f"🔍 Starting investigation: {args.goal}")
    print(f"   Max turns: {config.max_turns} | LLM: {config.llm_provider}")
    print()

    session = await agent.investigate(args.goal)

    # Print results
    print("\n" + "=" * 60)
    print(f"INVESTIGATION COMPLETE — {session.goal}")
    print("=" * 60)

    summary = session.summary()
    print(f"  Turns:    {summary['turns']}")
    print(f"  Entities: {summary['entity_count']}")
    print(f"  Findings: {summary['finding_count']}")
    print(f"  Leads:    {summary['leads_open']} open / {summary['leads_total']} total")
    print(f"  Tools:    {', '.join(summary['unique_tools'])}")

    if session.findings:
        print(f"\nFINDINGS:")
        for f in session.findings:
            print(f"  [{f.source}] {f.summary}")

    if session.get_open_leads():
        print(f"\nUNRESOLVED LEADS:")
        for l in session.get_open_leads()[:5]:
            print(f"  [{l.priority:.1f}] {l.description}")

    if session.reasoning_trace:
        print(f"\nREASONING TRACE:")
        for step in session.reasoning_trace:
            print(f"  → {step}")

    # Save output
    if args.output:
        output = {
            "summary": summary,
            "findings": [
                {"source": f.source, "summary": f.summary, "confidence": f.confidence}
                for f in session.findings
            ],
            "entities": list(session.entities.values()),
            "reasoning": session.reasoning_trace,
        }
        with open(args.output, "w") as fp:
            json.dump(output, fp, indent=2)
        print(f"\nSaved to {args.output}")


async def _cmd_search(args: argparse.Namespace) -> None:
    """Quick entity search."""
    from emet.mcp.tools import EmetToolExecutor

    executor = EmetToolExecutor()
    params: dict[str, Any] = {
        "query": args.query,
        "entity_type": args.type,
        "limit": args.limit,
    }
    if args.source:
        params["sources"] = args.source

    print(f"🔍 Searching: {args.query}")
    result = await executor.execute("search_entities", params)

    entities = result.get("entities", [])
    print(f"Found {len(entities)} entities:\n")

    for entity in entities:
        schema = entity.get("schema", "?")
        props = entity.get("properties", {})
        names = props.get("name", [])
        name = names[0] if names else entity.get("id", "?")[:20]
        country = ", ".join(props.get("country", props.get("jurisdiction", [])))
        prov = entity.get("_provenance", {}).get("source", "?")
        print(f"  [{schema}] {name}" + (f" ({country})" if country else "") + f"  — {prov}")


async def _cmd_workflow(args: argparse.Namespace) -> None:
    """Run a predefined investigation workflow."""
    from emet.workflows import WorkflowRegistry, WorkflowEngine
    from emet.mcp.tools import EmetToolExecutor

    registry = WorkflowRegistry()
    registry.load_builtins()

    wf = registry.get(args.name)
    if not wf:
        available = [w.name for w in registry.list_workflows()]
        print(f"Unknown workflow: {args.name}")
        print(f"Available: {', '.join(available)}")
        sys.exit(1)

    inputs = {"target": args.target, **args.params}

    if args.dry_run:
        print(f"DRY RUN: {wf.name} v{wf.version}")
        print(f"  Steps: {len(wf.steps)}")
        for step in wf.steps:
            print(f"    {step.id}: {step.tool} → {step.params}")
        return

    executor = EmetToolExecutor()
    engine = WorkflowEngine(executor=executor)

    print(f"🔄 Running workflow: {wf.name}")
    run = await engine.execute(wf, inputs)

    print(f"\nStatus: {run.status.value}")
    print(f"Steps: {len(run.step_results)}")
    for step_id, result in run.step_results.items():
        status = result.get("_status", "?")
        print(f"  {step_id}: {status}")


def _cmd_serve(args: argparse.Namespace) -> None:
    """Start MCP server."""
    from emet.mcp.server import create_server

    print(f"Starting Emet MCP server (transport: {args.transport})")
    server = create_server()

    if args.transport == "stdio":
        import mcp.server.stdio
        asyncio.run(
            mcp.server.stdio.run_server(server)
        )
    else:
        print(f"Transport {args.transport} not yet implemented")
        sys.exit(1)


def _cmd_status() -> None:
    """Show system status."""
    print("EMET — Investigative Journalism Agent")
    print("=" * 40)

    # Modules
    modules = {
        "cognition": "emet.cognition",
        "skills": "emet.skills",
        "ftm": "emet.ftm",
        "graph": "emet.graph",
        "mcp": "emet.mcp",
        "workflows": "emet.workflows",
        "agent": "emet.agent",
        "export": "emet.export",
        "monitoring": "emet.monitoring",
    }

    for name, module_path in modules.items():
        try:
            __import__(module_path)
            print(f"  {name:15s} ✓")
        except Exception as e:
            print(f"  {name:15s} ✗ ({e})")

    # Skills
    try:
        from emet.skills import get_chip, SKILL_CHIP_REGISTRY
        loaded = len(SKILL_CHIP_REGISTRY)
        total = loaded
        print(f"\n  Skill chips: {loaded}/{total}")
    except Exception:
        print(f"\n  Skill chips: unavailable")

    # Workflows
    try:
        from emet.workflows import WorkflowRegistry
        reg = WorkflowRegistry()
        reg.load_builtins()
        print(f"  Workflows:   {len(reg.list_workflows())}")
    except Exception:
        print(f"  Workflows:   unavailable")

    # LLM
    try:
        from emet.config.settings import settings
        print(f"\n  LLM:         {settings.llm_provider}")
        print(f"  Ollama URL:  {settings.ollama_base_url}")
    except Exception:
        print(f"\n  LLM:         (config unavailable)")


if __name__ == "__main__":
    main()
