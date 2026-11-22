"""Neo4j sync utilities.
Extracts platform graph from database and performs idempotent MERGE into Neo4j.
Can be executed as a module: `python -m app.graph.sync`.
"""
import logging
from typing import Any, Dict

from app.graph.build import _build_from_db
from app.graph.neo4j_client import get_driver, is_neo4j_configured

logger = logging.getLogger("app.graph.sync")


def sync_all() -> Dict[str, Any]:
    """Sync the full database graph into Neo4j using batched UNWIND ... MERGE."""
    if not is_neo4j_configured():
        logger.info("Neo4j not configured; skipping sync.")
        return {"status": "skipped", "reason": "not_configured"}

    driver = get_driver()
    if not driver:
        logger.warning("Neo4j driver unavailable; skipping sync.")
        return {"status": "skipped", "reason": "unavailable"}

    try:
        # Build platform graph with admin-level viewer (all public and private projects)
        admin_viewer = {"id": 0, "role": "admin"}
        graph = _build_from_db("platform", 0, admin_viewer)
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        with driver.session() as session:
            # 1. Group nodes by type for MERGE with dynamic labels
            nodes_by_type: Dict[str, list] = {}
            for n in nodes:
                ntype = n.get("type", "Node")
                nodes_by_type.setdefault(ntype, []).append({
                    "id": n["id"],
                    "label": n.get("label", ""),
                    "props": n.get("props", {}),
                })

            for ntype, nlist in nodes_by_type.items():
                query = f"""
                UNWIND $batch AS item
                MERGE (n:{ntype} {{id: item.id}})
                SET n.label = item.label, n += item.props
                """
                session.run(query, batch=nlist)

            # 2. Batch merge edges
            edges_by_type: Dict[str, list] = {}
            for e in edges:
                etype = e.get("type", "RELATED_TO")
                edges_by_type.setdefault(etype, []).append({
                    "source": e["source"],
                    "target": e["target"],
                })

            for etype, elist in edges_by_type.items():
                query = f"""
                UNWIND $batch AS edge
                MATCH (a {{id: edge.source}})
                MATCH (b {{id: edge.target}})
                MERGE (a)-[r:{etype}]->(b)
                """
                session.run(query, batch=elist)

        logger.info("Successfully synced %d nodes and %d edges to Neo4j.", len(nodes), len(edges))
        return {"status": "ok", "nodes": len(nodes), "edges": len(edges)}
    except Exception as exc:
        logger.warning("Neo4j sync failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def on_event(event_type: str, **kwargs: Any) -> None:
    """Non-blocking event hook for contribution submit, review, and accept.
    Upserts changed nodes/edges. Never raises into the caller.
    """
    if not is_neo4j_configured():
        return
    try:
        driver = get_driver()
        if not driver:
            return

        with driver.session() as session:
            if event_type == "contribution_submit":
                cid = kwargs.get("contribution_id")
                mid = kwargs.get("milestone_id")
                uid = kwargs.get("user_id")
                title = kwargs.get("title", f"Contribution {cid}")
                ai_dec = kwargs.get("ai_declaration", "human")
                if cid and mid and uid:
                    session.run(
                        """
                        MERGE (c:Contribution {id: $cid})
                        SET c.label = $title, c.ai_declaration = $ai_dec, c.status = 'submitted'
                        MERGE (u:User {id: $uid})
                        MERGE (m:Milestone {id: $mid})
                        MERGE (u)-[:AUTHORED]->(c)
                        MERGE (c)-[:FOR]->(m)
                        """,
                        cid=f"c_{cid}",
                        mid=f"m_{mid}",
                        uid=f"u_{uid}",
                        title=title,
                        ai_dec=ai_dec,
                    )
            elif event_type == "contribution_review":
                rid = kwargs.get("review_id")
                cid = kwargs.get("contribution_id")
                uid = kwargs.get("reviewer_id")
                dec = kwargs.get("decision", "pending")
                if rid and cid and uid:
                    session.run(
                        """
                        MERGE (r:Review {id: $rid})
                        SET r.label = $label, r.decision = $dec
                        MERGE (c:Contribution {id: $cid})
                        MERGE (u:User {id: $uid})
                        MERGE (r)-[:REVIEWS]->(c)
                        MERGE (u)-[:REVIEWED]->(r)
                        """,
                        rid=f"r_{rid}",
                        cid=f"c_{cid}",
                        uid=f"u_{uid}",
                        label=f"Review ({dec})",
                        dec=dec,
                    )
            elif event_type == "milestone_accept":
                mid = kwargs.get("milestone_id")
                if mid:
                    session.run(
                        """
                        MATCH (m:Milestone {id: $mid})
                        SET m.status = 'accepted'
                        """,
                        mid=f"m_{mid}",
                    )
    except Exception as exc:
        logger.warning("graph.on_event failed silently: %s", exc)


if __name__ == "__main__":
    import sys
    res = sync_all()
    print("Sync Result:", res)
    sys.exit(0 if res.get("status") in ("ok", "skipped") else 1)
