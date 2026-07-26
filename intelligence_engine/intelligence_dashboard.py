"""Compatibility entry point for the Stage × Group × RS sidecar dashboard."""

from .stage_dashboard import build_html, generate, load_payload, main

__all__ = ["build_html", "generate", "load_payload", "main"]


if __name__ == "__main__":
    main()
