"""
app/splits.py — Split Engine for Provenance.

Pure functions only. No database access.
All money calculations use fractions.Fraction and produce integer rupees.
Guarantees: sum(experts) + sum(students) + fee + ai_reserve == amount_inr.
"""
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence


DEFAULT_CONFIG: Dict[str, float] = {
    "fee": 0.10,
    "ai_reserve": 0.05,
    "expert_share": 0.30,
    "equal_part": 0.40,
}


def validate_config(config: Dict[str, Any]) -> None:
    """Validate split configuration parameters.

    Raises ValueError if any value is below 0 or above 1, or if fee + ai_reserve >= 1.
    """
    for key in ("fee", "ai_reserve", "expert_share", "equal_part"):
        if key not in config:
            raise ValueError(f"Missing required config key: '{key}'")
        val = config[key]
        if not isinstance(val, (int, float, Fraction)):
            raise ValueError(f"Config key '{key}' must be a number, got {type(val)}")
        f_val = Fraction(str(val))
        if f_val < 0 or f_val > 1:
            raise ValueError(f"Config key '{key}' must be between 0 and 1, got {val}")

    fee_f = Fraction(str(config["fee"]))
    ai_reserve_f = Fraction(str(config["ai_reserve"]))
    if fee_f + ai_reserve_f >= 1:
        raise ValueError(
            f"fee ({config['fee']}) + ai_reserve ({config['ai_reserve']}) must be less than 1"
        )


def _round_half_up(f: Fraction) -> int:
    """Standard half-up rounding for non-negative Fractions to integers."""
    if f < 0:
        return -_round_half_up(-f)
    return (f.numerator * 2 + f.denominator) // (f.denominator * 2)


def compute_split(
    amount_inr: int,
    student_weights: Dict[Any, Any],
    expert_ids: Sequence[Any],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute financial split for a milestone amount.

    Args:
        amount_inr: Non-negative integer milestone amount in INR.
        student_weights: Dict of {student_id: weight}. Must have at least 1 student.
        expert_ids: Sequence of expert user IDs.
        config: Optional custom configuration dict overriding DEFAULT_CONFIG.

    Returns:
        Dict containing full split breakdown and participant share maps.
    """
    if not isinstance(amount_inr, int) or isinstance(amount_inr, bool) or amount_inr < 0:
        raise ValueError("amount_inr must be a non-negative integer")

    if not student_weights:
        raise ValueError("no eligible students")

    for uid, w in student_weights.items():
        if not isinstance(w, (int, float, Fraction)):
            raise ValueError(f"Weight for student {uid} must be a number")
        if Fraction(str(w)) < 0:
            raise ValueError(f"Weight for student {uid} cannot be negative")

    cfg: Dict[str, Any] = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)
    validate_config(cfg)

    fee_rate = Fraction(str(cfg["fee"]))
    ai_reserve_rate = Fraction(str(cfg["ai_reserve"]))
    expert_share_rate = Fraction(str(cfg["expert_share"]))
    equal_part_rate = Fraction(str(cfg["equal_part"]))

    amount_f = Fraction(amount_inr, 1)

    # 1. Platform Fee & AI Reserve (rounded half up)
    fee_inr = _round_half_up(amount_f * fee_rate)
    ai_reserve_inr = _round_half_up(amount_f * ai_reserve_rate)

    # Cap if sum exceeds total (e.g. edge cases on small amounts)
    if fee_inr + ai_reserve_inr > amount_inr:
        fee_inr = min(fee_inr, amount_inr)
        ai_reserve_inr = amount_inr - fee_inr

    net_inr = amount_inr - fee_inr - ai_reserve_inr
    net_f = Fraction(net_inr, 1)

    # 2. Expert Pool
    # If no experts, expert pool is added to the student pool (SPEC §18, Check 48)
    expert_list = list(expert_ids)
    if not expert_list:
        experts: Dict[Any, int] = {}
        expert_pool_inr = 0
        student_pool_inr = net_inr
    else:
        expert_pool_f = net_f * expert_share_rate
        target_expert_pool = _round_half_up(expert_pool_f)
        target_expert_pool = min(target_expert_pool, net_inr)

        num_experts = len(expert_list)
        floor_expert = target_expert_pool // num_experts
        rem_experts = target_expert_pool % num_experts

        # Largest remainder tie broken by lowest ID
        sorted_expert_ids = sorted(expert_list)
        experts = {}
        for i, eid in enumerate(sorted_expert_ids):
            extra = 1 if i < rem_experts else 0
            experts[eid] = floor_expert + extra

        expert_pool_inr = sum(experts.values())
        student_pool_inr = net_inr - expert_pool_inr

    # 3. Student Pool (Equal vs Weighted)
    student_pool_f = Fraction(student_pool_inr, 1)
    equal_part_total_f = student_pool_f * equal_part_rate
    weighted_part_total_f = student_pool_f - equal_part_total_f

    equal_part_total_inr = _round_half_up(equal_part_total_f)
    weighted_part_total_inr = student_pool_inr - equal_part_total_inr

    num_students = len(student_weights)
    weights_f = {uid: Fraction(str(w)) for uid, w in student_weights.items()}
    total_weight = sum(weights_f.values())

    # All-zero weights split equally (Check 48)
    if total_weight == 0:
        weight_shares = {uid: Fraction(1, num_students) for uid in student_weights}
    else:
        weight_shares = {uid: weights_f[uid] / total_weight for uid in student_weights}

    exact_equal_share = equal_part_total_f / num_students
    exact_shares: Dict[Any, Fraction] = {}
    for uid in student_weights:
        exact_weighted = weighted_part_total_f * weight_shares[uid]
        exact_shares[uid] = exact_equal_share + exact_weighted

    # Largest-remainder rounding for students
    floor_shares = {uid: int(exact_shares[uid]) for uid in student_weights}
    remainders = {uid: exact_shares[uid] - floor_shares[uid] for uid in student_weights}

    allocated_floors = sum(floor_shares.values())
    rem_to_distribute = student_pool_inr - allocated_floors

    # Sort students: higher remainder first;
    # Ties broken by: LOWEST weight, then lowest user id (SPEC §18, Check 46)
    def _student_sort_key(uid: Any):
        return (-remainders[uid], weights_f[uid], uid)

    sorted_students = sorted(student_weights.keys(), key=_student_sort_key)
    bonus_uids = set(sorted_students[:rem_to_distribute])

    students: Dict[Any, Dict[str, Any]] = {}
    for uid in student_weights:
        rounding_adj = 1 if uid in bonus_uids else 0
        allocated = floor_shares[uid] + rounding_adj
        w_val = weights_f[uid]
        weight_display = float(w_val) if w_val.denominator != 1 else int(w_val)

        students[uid] = {
            "amount_inr": allocated,
            "weight": weight_display,
            "weight_share": round(float(weight_shares[uid]), 2),
            "equal_part": round(float(exact_equal_share), 2),
            "weighted_part": round(float(weighted_part_total_f * weight_shares[uid]), 2),
            "rounding_adjustment": rounding_adj,
        }

    # Strict conservation assertion
    assert sum(experts.values()) + sum(s["amount_inr"] for s in students.values()) + fee_inr + ai_reserve_inr == amount_inr

    return {
        "amount_inr": amount_inr,
        "fee_inr": fee_inr,
        "ai_reserve_inr": ai_reserve_inr,
        "net_inr": net_inr,
        "expert_pool_inr": expert_pool_inr,
        "student_pool_inr": student_pool_inr,
        "equal_part_total_inr": equal_part_total_inr,
        "weighted_part_total_inr": weighted_part_total_inr,
        "experts": experts,
        "students": students,
        "config": cfg,
    }
