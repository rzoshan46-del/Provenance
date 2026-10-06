import json
from app.db import execute, query_one

SYNTHETIC_USERS = [
    {
        "id": 1,
        "name": "Admin Asha",
        "email": "asha@example.com",
        "role": "admin",
        "verification_level": 3,
        "institution": "Provenance Foundation",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["governance", "audit", "dispute_resolution", "identity_verification"]),
        "bio": "System administrator and integrity auditor for Provenance ecosystem.",
    },
    {
        "id": 2,
        "name": "Meera Rao",
        "email": "meera.rao@example.com",
        "role": "sponsor",
        "verification_level": 2,
        "institution": "MedVision Labs",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["clinical research", "project sponsorship", "ophthalmology", "budget_planning"]),
        "bio": "Lead clinical innovator at MedVision Labs sponsoring edge AI healthcare diagnostics.",
    },
    {
        "id": 3,
        "name": "Arvind Nair",
        "email": "arvind.nair@example.com",
        "role": "expert",
        "verification_level": 2,
        "institution": "Apex AI Institute",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["medical imaging", "deep learning", "edge deployment"]),
        "bio": "Senior domain expert with 10+ years specializing in edge medical computer vision.",
    },
    {
        "id": 4,
        "name": "Kiran Shah",
        "email": "kiran.shah@example.com",
        "role": "expert",
        "verification_level": 2,
        "institution": "BioScan Tech",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps(["MedVision Labs"]),
        "skills": json.dumps(["medical imaging", "deep learning", "edge deployment"]),
        "bio": "Edge AI specialist with prior advisory affiliation at MedVision Labs.",
    },
    {
        "id": 5,
        "name": "Ananya",
        "email": "ananya@example.com",
        "role": "student",
        "verification_level": 1,
        "institution": "Garden City University",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["python", "pytorch", "medical imaging", "data analysis"]),
        "bio": "Computer science graduate researcher working on CNN image classification.",
    },
    {
        "id": 6,
        "name": "Rahul",
        "email": "rahul@example.com",
        "role": "student",
        "verification_level": 1,
        "institution": "Garden City University",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["edge deployment", "tensorrt", "embedded systems", "c++"]),
        "bio": "Undergraduate developer specializing in embedded systems and model quantization.",
    },
    {
        "id": 7,
        "name": "Sneha",
        "email": "sneha@example.com",
        "role": "student",
        "verification_level": 2,
        "institution": "National Tech Institute",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["data curation", "evaluation metrics", "fairness", "python"]),
        "bio": "Data science researcher focused on clinical benchmark curation and algorithmic fairness.",
    },
    {
        "id": 8,
        "name": "Vikram",
        "email": "vikram@example.com",
        "role": "student",
        "verification_level": 1,
        "institution": "Garden City University",
        "is_minor": 0,
        "guardian_consent": 1,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["fastapi", "fullstack", "ui design", "sqlite"]),
        "bio": "Software engineering student passionate about research workspace tooling and APIs.",
    },
    {
        "id": 9,
        "name": "Tara",
        "email": "tara@example.com",
        "role": "student",
        "verification_level": 1,
        "institution": "Garden City University",
        "is_minor": 1,
        "guardian_consent": 0,
        "conflict_orgs": json.dumps([]),
        "skills": json.dumps(["python", "machine learning", "dataset labeling"]),
        "bio": "High school talent researcher in AI fundamentals; minor status awaiting guardian consent.",
    },
]


from app.services.projects import canonical_charter_hash


def seed_users() -> None:
    """Insert the 9 synthetic users idempotently."""
    existing = query_one("SELECT COUNT(*) as count FROM users")
    if existing and existing["count"] > 0:
        return

    for u in SYNTHETIC_USERS:
        execute(
            """
            INSERT INTO users (
                id, name, email, role, verification_level, institution,
                is_minor, guardian_consent, conflict_orgs, skills, bio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                u["id"],
                u["name"],
                u["email"],
                u["role"],
                u["verification_level"],
                u["institution"],
                u["is_minor"],
                u["guardian_consent"],
                u["conflict_orgs"],
                u["skills"],
                u["bio"],
            ),
        )


def seed_projects() -> None:
    """Insert seeded projects P1 and P2 idempotently with charter v1, no members and no milestones."""
    existing = query_one("SELECT COUNT(*) as count FROM projects")
    if existing and existing["count"] > 0:
        return

    now_iso = "2026-10-05T08:00:00+00:00"

    # P1: Funded and confidential
    p1_terms = {
        "engagement_model": "funded",
        "rewards": "INR 1,00,000 milestone escrow pool distributed according to Section 8 split rules.",
        "scope": "Edge-optimized CNN architecture and quantization for diabetic retinopathy screening on mobile fundus devices.",
        "people": "1 sponsor, 1 expert lead, 3 student researchers.",
        "ip_publication": "Open-access research publication with named student and expert co-authorship; sponsor receives non-exclusive commercial implementation rights.",
        "confidentiality": "Confidential brief and calibration data protected under project charter.",
        "credit_split": "Split engine: 10% platform fee, 5% AI compute reserve, expert 30% of net (INR 25,500), student pool 70% of net split 40% equal and 60% by verified contribution impact weight.",
        "exit_disputes": "Pro-rata credit retention on departure; disputes resolved by Admin Asha via ledger audit.",
        "commercialisation": "Future commercial spin-offs require separate commercialization agreements and royalty schedules.",
    }
    p1_public_summary = (
        "MedVision Labs is sponsoring an open collaborative challenge to develop an ultra-lightweight deep learning pipeline "
        "for diabetic retinopathy detection on low-cost edge fundus cameras. The project aims to enable rapid rural screening "
        "with real-time on-device inference under strict compute constraints. Contributors will collaborate on dataset curation, "
        "quantization, and clinical benchmark validation."
    )
    p1_confidential_brief = (
        "[SYNTHETIC RESEARCH BRIEF - NOT FOR PUBLIC DISTRIBUTION]\n"
        "Target Hardware: ARM Cortex-A53 quad-core edge camera module with 1GB shared memory.\n"
        "Inference Latency Limit: Under 350ms per fundus frame at 512x512 resolution.\n"
        "Clinical Sensitivity Target: Minimum 92% sensitivity on Grade 2+ diabetic retinopathy lesions.\n"
        "Calibration Dataset: 1,500 synthetic multi-spectral fundus captures with synthetic microaneurysm labels (SimFundus-v1 synthetic benchmark).\n"
        "Quantization Constraints: INT8 quantization required using TensorRT or ONNX Runtime without accuracy drop > 1.5%.\n"
        "Proprietary Optical Profile: MedVision Edge-Cam distortion matrix v2.4 (embedded in proprietary camera firmware).\n"
        "Clinical Validation Protocol: Synthetic 5-fold cross validation with clinical expert review by Dr. Arvind Nair."
    )

    execute(
        """
        INSERT INTO projects (
            id, sponsor_id, title, public_summary, confidential_brief,
            sensitivity_label, engagement_model, status, current_charter_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            2,  # Meera Rao
            "Low-cost detection of diabetic retinopathy from fundus images on edge devices",
            p1_public_summary,
            p1_confidential_brief,
            "confidential",
            "funded",
            "open",
            1,
            now_iso,
        ),
    )
    p1_hash = canonical_charter_hash(1, p1_terms)
    execute(
        """
        INSERT INTO charters (project_id, version, terms_json, hash, published_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (1, 1, json.dumps(p1_terms), p1_hash, now_iso),
    )

    # P2: Knowledge sharing, internal, strictly UNPAID
    p2_terms = {
        "engagement_model": "knowledge_sharing",
        "rewards": "UNPAID: recognition only (certificates, digital badges, academic co-authorship, recommendation letters). No payment provided.",
        "scope": "Standardized annotation protocols and benchmark dataset for retinal image grading quality.",
        "people": "Domain experts and student volunteers collaborating on open science data curation.",
        "ip_publication": "Creative Commons CC-BY-4.0 open dataset and open-access benchmark paper.",
        "confidentiality": "Internal research drafts and quality assessment rubrics.",
        "credit_split": "Equal co-authorship and credential badges based on reviewed contributions. No payment distributed.",
        "exit_disputes": "Voluntary departure with authorship credit retained for accepted contributions. No payment involved.",
        "commercialisation": "Open science asset. If later commercialised, contributors keep authorship credit and are notified; this remains unpaid with no payment unless a new charter version is accepted.",
    }
    p2_public_summary = (
        "An open research initiative establishing standardized annotation rubrics and quality evaluation benchmarks for retinal imagery. "
        "Contributors collaborate to curate reference guidelines that improve consistency across multi-center imaging studies. "
        "Work is conducted as an open scientific contribution for academic recognition and community reference."
    )
    p2_confidential_brief = (
        "[INTERNAL RESEARCH GUIDELINES]\n"
        "Annotation Rubric: 4-tier image clarity scale (ungradable, poor, acceptable, excellent).\n"
        "Feature Checklists: Optic disc sharpness, macula visibility, illumination uniformity.\n"
        "Reference Annotations: 500 expert-reviewed sample image guidelines.\n"
        "Tooling Requirements: Browser-based open grading rubrics and consensus scoring documentation.\n"
        "Synthetic Evaluation: Anonymized synthetic quality metrics for inter-rater reliability calibration."
    )

    execute(
        """
        INSERT INTO projects (
            id, sponsor_id, title, public_summary, confidential_brief,
            sensitivity_label, engagement_model, status, current_charter_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            2,
            2,  # Meera Rao
            "Open annotation guidelines and benchmark for retinal image quality",
            p2_public_summary,
            p2_confidential_brief,
            "internal",
            "knowledge_sharing",
            "open",
            1,
            now_iso,
        ),
    )
    p2_hash = canonical_charter_hash(1, p2_terms)
    execute(
        """
        INSERT INTO charters (project_id, version, terms_json, hash, published_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (2, 1, json.dumps(p2_terms), p2_hash, now_iso),
    )

