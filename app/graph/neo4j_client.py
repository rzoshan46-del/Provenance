"""Neo4j client wrapper with lazy connection and health checking.
"""
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("app.graph.neo4j")

_driver: Optional[Any] = None


def is_neo4j_configured() -> bool:
    """Return True if all Neo4j environment variables are set."""
    uri = os.getenv("NEO4J_URI", "").strip()
    user = os.getenv("NEO4J_USER", "").strip()
    pwd = os.getenv("NEO4J_PASSWORD", "").strip()
    return bool(uri and user and pwd)


def get_driver() -> Optional[Any]:
    """Return the active Neo4j driver or lazily initialize one. Never connects on import."""
    global _driver
    if _driver is not None:
        return _driver

    if not is_neo4j_configured():
        return None

    uri = os.getenv("NEO4J_URI", "").strip()
    user = os.getenv("NEO4J_USER", "").strip()
    pwd = os.getenv("NEO4J_PASSWORD", "").strip()

    try:
        from neo4j import GraphDatabase

        _driver = GraphDatabase.driver(
            uri,
            auth=(user, pwd),
            connection_timeout=5.0,
            max_connection_lifetime=3600,
        )
        return _driver
    except Exception as exc:
        logger.warning("Failed to initialize Neo4j driver: %s", exc)
        _driver = None
        return None


def close_driver() -> None:
    """Close the active driver instance."""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        except Exception:
            pass
        _driver = None


def get_neo4j_status() -> str:
    """Check Neo4j connectivity and return 'ok', 'unavailable', or 'not_configured'."""
    if not is_neo4j_configured():
        return "not_configured"
    driver = get_driver()
    if not driver:
        return "unavailable"
    try:
        with driver.session() as session:
            result = session.run("RETURN 1 AS alive")
            record = result.single()
            if record and record["alive"] == 1:
                return "ok"
            return "unavailable"
    except Exception as exc:
        logger.warning("Neo4j health check failed: %s", exc)
        return "unavailable"
