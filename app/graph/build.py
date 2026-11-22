"""Graph building utilities.
Extracts nodes and edges from SQLite or Neo4j respecting permission and redaction boundaries.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Set

from app.access import can_view
from app.db import query_all, query_one
from app.graph.neo4j_client import get_driver, is_neo4j_configured
from app.profiles import get_initials

logger = logging.getLogger("app.graph.build")

MAX_NODES = 300


def _get_user_display_name(target_user: Any, viewer: Optional[Any]) -> str:
    """Format user name respecting privacy and minor protections."""
    u_dict = dict(target_user) if target_user else {}
    is_minor = bool(u_dict.get("is_minor") == 1)
    name = u_dict.get("name") or "User"
    if is_minor:
        return get_initials(name)

    user_id = u_dict["id"]
    v_dict = dict(viewer) if viewer else {}
    if v_dict and (v_dict.get("id") == user_id or v_dict.get("role") == "admin"):
        return name

    # Check user_profiles.is_public
    prof = query_one("SELECT is_public FROM user_profiles WHERE user_id = ?", (user_id,))
    is_public = prof["is_public"] if prof and prof["is_public"] is not None else 1

    if is_public == 1:
        return name

    # Check if viewer shares a project membership with this user
    if v_dict and v_dict.get("id"):
        shared = query_one(
            """
            SELECT 1 FROM charter_acceptances ca1
            JOIN charter_acceptances ca2 ON ca1.project_id = ca2.project_id
            WHERE ca1.user_id = ? AND ca2.user_id = ? AND ca1.engagement_model_ack = 1 AND ca2.engagement_model_ack = 1
            LIMIT 1
            """,
            (user_id, v_dict["id"]),
        )
        if shared:
            return name

    return f"User {user_id}"


def _build_from_db(scope: str, item_id: Any, viewer: Optional[Any]) -> Dict[str, Any]:
    """Build graph from SQLite database."""
    v_dict = dict(viewer) if viewer else None
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    node_ids: Set[str] = set()

    def add_node(nid: str, ntype: str, label: str, props: Dict[str, Any]) -> None:
        if nid not in node_ids and len(nodes) < MAX_NODES:
            node_ids.add(nid)
            clean_props = {k: v for k, v in props.items() if k not in ("confidential_brief", "artefact_text")}
            nodes.append({"id": nid, "type": ntype, "label": label, "props": clean_props})

    def add_edge(source: str, target: str, etype: str) -> None:
        if source in node_ids and target in node_ids and len(edges) < MAX_NODES * 2:
            edges.append({"source": source, "target": target, "type": etype})

    # Determine allowed projects
    raw_projects = query_all("SELECT * FROM projects")
    all_projects = [dict(p) for p in raw_projects]
    allowed_project_ids = set()
    for p in all_projects:
        if p.get("sensitivity_label") == "public" or can_view(v_dict, p, "milestones"):
            allowed_project_ids.add(p["id"])

    scoped_project_id = None
    scoped_user_id = None
    scoped_contrib_id = None

    if scope == "project":
        proj_id_int = int(item_id)
        if proj_id_int not in allowed_project_ids:
            return {"nodes": [], "edges": [], "source": "database", "error": "forbidden"}
        scoped_project_id = proj_id_int
    elif scope == "contribution":
        scoped_contrib_id = int(item_id)
        c_row = query_one("SELECT milestone_id FROM contributions WHERE id = ?", (scoped_contrib_id,))
        if not c_row:
            return {"nodes": [], "edges": [], "source": "database", "error": "not_found"}
        m_row = query_one("SELECT project_id FROM milestones WHERE id = ?", (c_row["milestone_id"],))
        if not m_row or m_row["project_id"] not in allowed_project_ids:
            return {"nodes": [], "edges": [], "source": "database", "error": "forbidden"}
        scoped_project_id = m_row["project_id"]
    elif scope == "profile":
        scoped_user_id = int(item_id)
        u_target = query_one("SELECT * FROM users WHERE id = ?", (scoped_user_id,))
        if not u_target:
            return {"nodes": [], "edges": [], "source": "database", "error": "not_found"}

    # 1. Projects
    projects_to_fetch = [p for p in all_projects if p["id"] in allowed_project_ids]
    if scoped_project_id:
        projects_to_fetch = [p for p in projects_to_fetch if p["id"] == scoped_project_id]

    proj_dict = {p["id"]: p for p in projects_to_fetch}
    for p in projects_to_fetch:
        add_node(f"p_{p['id']}", "Project", p["title"], {
            "status": p.get("status", ""),
            "engagement_model": p.get("engagement_model", ""),
            "sensitivity": p.get("sensitivity_label", ""),
        })

    # 2. Users
    raw_users = query_all("SELECT * FROM users")
    user_dict = {u["id"]: dict(u) for u in raw_users}

    # Project Sponsors
    for p in projects_to_fetch:
        s_id = p.get("sponsor_id")
        if s_id and s_id in user_dict:
            u = user_dict[s_id]
            add_node(f"u_{u['id']}", "User", _get_user_display_name(u, v_dict), {
                "role": u.get("role", ""),
                "verification_level": u.get("verification_level", 0),
            })
            add_edge(f"u_{u['id']}", f"p_{p['id']}", "SPONSORS")

    # 3. Milestones
    if proj_dict:
        proj_ids_tuple = tuple(proj_dict.keys())
        placeholders = ",".join("?" for _ in proj_ids_tuple)
        raw_milestones = query_all(
            f"SELECT id, project_id, title, status, amount_inr FROM milestones WHERE project_id IN ({placeholders})",
            proj_ids_tuple,
        )
        milestones = [dict(m) for m in raw_milestones]
    else:
        milestones = []

    milestone_dict = {m["id"]: m for m in milestones}
    for m in milestones:
        add_node(f"m_{m['id']}", "Milestone", m["title"], {
            "status": m.get("status", ""),
            "amount_inr": m.get("amount_inr", 0),
        })
        add_edge(f"m_{m['id']}", f"p_{m['project_id']}", "PART_OF")

    # 4. Contributions
    if milestone_dict:
        m_ids_tuple = tuple(milestone_dict.keys())
        m_placeholders = ",".join("?" for _ in m_ids_tuple)
        contrib_query = f"SELECT id, milestone_id, author_id, artefact_title, ai_declaration, review_status FROM contributions WHERE milestone_id IN ({m_placeholders})"
        params = list(m_ids_tuple)
        if scoped_contrib_id:
            contrib_query += " AND id = ?"
            params.append(scoped_contrib_id)
        raw_contributions = query_all(contrib_query, tuple(params))
        contributions = [dict(c) for c in raw_contributions]
    else:
        contributions = []

    contrib_dict = {c["id"]: c for c in contributions}
    for c in contributions:
        add_node(f"c_{c['id']}", "Contribution", c["artefact_title"], {
            "ai_declaration": c.get("ai_declaration", ""),
            "status": c.get("review_status", ""),
        })
        add_edge(f"c_{c['id']}", f"m_{c['milestone_id']}", "FOR")
        # Author User
        a_id = c.get("author_id")
        if a_id and a_id in user_dict:
            u = user_dict[a_id]
            add_node(f"u_{u['id']}", "User", _get_user_display_name(u, v_dict), {
                "role": u.get("role", ""),
                "verification_level": u.get("verification_level", 0),
            })
            add_edge(f"u_{u['id']}", f"c_{c['id']}", "AUTHORED")

    # 5. Reviews
    if contrib_dict:
        c_ids_tuple = tuple(contrib_dict.keys())
        c_placeholders = ",".join("?" for _ in c_ids_tuple)
        raw_reviews = query_all(
            f"SELECT id, contribution_id, reviewer_id, decision FROM reviews WHERE contribution_id IN ({c_placeholders})",
            c_ids_tuple,
        )
        reviews = [dict(r) for r in raw_reviews]
    else:
        reviews = []

    for r in reviews:
        add_node(f"r_{r['id']}", "Review", f"Review ({r.get('decision', '')})", {
            "decision": r.get("decision", ""),
        })
        add_edge(f"r_{r['id']}", f"c_{r['contribution_id']}", "REVIEWS")
        rev_user_id = r.get("reviewer_id")
        if rev_user_id and rev_user_id in user_dict:
            u = user_dict[rev_user_id]
            add_node(f"u_{u['id']}", "User", _get_user_display_name(u, v_dict), {
                "role": u.get("role", ""),
                "verification_level": u.get("verification_level", 0),
            })
            add_edge(f"u_{u['id']}", f"r_{r['id']}", "REVIEWED")

    # 6. Credentials
    if proj_dict:
        raw_creds = query_all(
            f"SELECT id, project_id, user_id, kind FROM credentials WHERE project_id IN ({placeholders})",
            proj_ids_tuple,
        )
        credentials = [dict(cr) for cr in raw_creds]
        for cred in credentials:
            cid = f"cr_{cred['id']}"
            add_node(cid, "Credential", f"Cred: {cred.get('kind', '')}", {"kind": cred.get("kind", "")})
            matched_c = [c for c in contributions if c.get("author_id") == cred.get("user_id")]
            for mc in matched_c[:2]:
                add_edge(cid, f"c_{mc['id']}", "CERTIFIES")

    # 7. Skills
    for uid, u in user_dict.items():
        if f"u_{uid}" in node_ids:
            try:
                raw_skills = u.get("skills") or "[]"
                skill_list = json.loads(raw_skills) if isinstance(raw_skills, str) else []
                for s in skill_list[:3]:
                    s_id = f"s_{s.lower().replace(' ', '_')}"
                    add_node(s_id, "Skill", s, {})
                    add_edge(f"u_{uid}", s_id, "HAS_SKILL")
            except Exception:
                pass

    return {
        "nodes": nodes,
        "edges": edges,
        "source": "database",
    }


def _build_from_neo4j(scope: str, item_id: Any, viewer: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Build graph from Neo4j using Cypher queries."""
    driver = get_driver()
    if not driver:
        return None

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    node_ids: Set[str] = set()

    try:
        with driver.session() as session:
            if scope == "platform":
                cypher = """
                MATCH (n)
                OPTIONAL MATCH (n)-[r]->(m)
                RETURN n, r, m LIMIT 300
                """
                result = session.run(cypher)
            elif scope == "project":
                cypher = """
                MATCH (p:Project {id: $id})
                OPTIONAL MATCH (p)<-[r1]-(n)
                OPTIONAL MATCH (n)<-[r2]-(m)
                RETURN p AS n, r1 AS r, n AS m
                LIMIT 300
                """
                result = session.run(cypher, id=f"p_{item_id}")
            else:
                return None

            for record in result:
                n = record.get("n")
                r = record.get("r")
                m = record.get("m")

                for entity in (n, m):
                    if entity and hasattr(entity, "id") and hasattr(entity, "labels"):
                        nid = str(entity.get("id") or entity.element_id)
                        if nid not in node_ids:
                            node_ids.add(nid)
                            ntype = list(entity.labels)[0] if entity.labels else "Node"
                            label = entity.get("title") or entity.get("name") or entity.get("label") or nid
                            props = dict(entity)
                            nodes.append({"id": nid, "type": ntype, "label": label, "props": props})

                if r and hasattr(r, "type"):
                    edges.append({
                        "source": str(r.start_node.get("id") or r.start_node.element_id),
                        "target": str(r.end_node.get("id") or r.end_node.element_id),
                        "type": r.type,
                    })

            if nodes:
                return {"nodes": nodes, "edges": edges, "source": "neo4j"}
            return None
    except Exception as exc:
        logger.warning("Neo4j graph query failed (%s); falling back to database", exc)
        return None


def build_graph(scope: str, item_id: Any = None, viewer: Optional[Any] = None) -> Dict[str, Any]:
    """Entrypoint to build graph.
    Returns: {"nodes": [...], "edges": [...], "source": "neo4j" | "database"}
    Never raises; returns empty graph on unexpected error.
    """
    try:
        if is_neo4j_configured():
            neo4j_res = _build_from_neo4j(scope, item_id, viewer)
            if neo4j_res:
                return neo4j_res

        return _build_from_db(scope, item_id, viewer)
    except Exception as exc:
        logger.exception("Failed to build graph: %s", exc)
        return {"nodes": [], "edges": [], "source": "database", "message": "graph generation error"}
