def main() -> None:
    """Entry point for the `dk-tax` command: serve MCP over stdio."""
    from dk_tax.server import server

    server.run()
