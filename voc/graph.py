"""VOC 판정 흐름 (LangGraph StateGraph).

validate ─(빈 입력)→ END
   │
 guard(개인정보 가리기)
   │
 policy_check ─(정책 해당: 해외 법인 등)→ 고정 문구로 record (LLM 미호출)
   │
 rule_match ─(메뉴명 있음)──────────────→ record
   │(없음)
   ├─(LLM 사용)→ agent_judge ─(오류)→ similar_fallback
   └─(LLM 미사용)────────────────────→ similar_fallback
 agent_judge / similar_fallback ─(처리 가능)→ record
                                 └(처리 불가)→ guidance → record
 record ─(누적 3 이상)→ lookup → END
        └──────────────────────→ END
"""
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import agent, llm
from .db import load_menus, load_policies
from .guidance import generate_guidance_with_source
from .pii import mask_pii
from .service import (FREQUENT_THRESHOLD, find_similar_voc, get_menu_counts, lookup_mock_db,
                      match_menus, match_policy, save_voc, validate_input)


class VocState(TypedDict, total=False):
    voc_text: str
    registrant_id: str
    input_validation: dict
    pii_found: list
    matched: list
    match_source: Optional[str]
    similar: Optional[dict]
    judge: Optional[dict]
    agent_error: Optional[str]
    policy: Optional[dict]
    guidance: Optional[str]
    guidance_source: Optional[str]
    voc_id: int
    created_at: str
    snapshot: dict
    frequent: list
    account: Any
    business: list
    lookup_summary: Optional[dict]
    steps: list


def build_graph(conn, menus, llm_on, policies=None):
    names = [m["name"] for m in menus]
    policies = load_policies() if policies is None else policies

    def step(state, name):
        return [*state.get("steps", []), name]

    def validate(s):
        v = validate_input(s.get("voc_text"), s.get("registrant_id"))
        return {"input_validation": v, "steps": step(s, "validate")}

    def guard(s):
        text, found = mask_pii(s["voc_text"].strip())
        found = list(dict.fromkeys([*s.get("pii_found", []), *found]))  # run_voc에서 먼저 가린 것과 합침
        return {"voc_text": text, "registrant_id": s["registrant_id"].strip(),
                "pii_found": found, "steps": step(s, "guard")}

    def policy_check(s):
        p = match_policy(s["voc_text"], policies)
        if not p:
            return {"policy": None, "steps": step(s, "policy_check")}
        return {"policy": p, "matched": [], "match_source": "policy", "guidance": p["message"],
                "guidance_source": "policy", "steps": step(s, "policy_check")}

    def rule_match(s):
        matched = match_menus(s["voc_text"], menus)
        return {"matched": matched, "match_source": "menu" if matched else None,
                "steps": step(s, "rule_match")}

    def agent_judge(s):
        r = agent.judge_voc(s["voc_text"])
        if "error" in r:
            return {"agent_error": r["error"], "steps": step(s, "agent_judge")}
        menus_ok = [m for m in dict.fromkeys(r["menus"]) if m in names]  # 등록 메뉴만 인정
        matched = menus_ok if r["processable"] else []
        return {"matched": matched, "match_source": "agent" if matched else None,
                "judge": r, "steps": step(s, "agent_judge")}

    def similar_fallback(s):
        sim = find_similar_voc(conn, s["voc_text"])
        return {"matched": sim["menus"] if sim else [], "similar": sim,
                "match_source": "similar" if sim else None, "steps": step(s, "similar_fallback")}

    def guidance(s):
        reason = (s.get("judge") or {}).get("reason")
        text, source = generate_guidance_with_source(s["voc_text"], use_api=llm_on, reason=reason)
        return {"guidance": text, "guidance_source": source, "steps": step(s, "guidance")}

    def record(s):
        matched = s.get("matched") or []
        reason = (f"정책: {s['policy']['id']}" if s.get("policy")
                  else (s.get("judge") or {}).get("reason"))
        voc_id, created_at = save_voc(
            conn, s["registrant_id"], s["voc_text"], matched, s.get("guidance"),
            s.get("guidance_source"), s.get("match_source"), s.get("similar"), reason)
        counts = get_menu_counts(conn)
        snapshot = {m: counts[m] for m in matched}
        frequent = [m for m in matched if snapshot[m] >= FREQUENT_THRESHOLD]
        return {"voc_id": voc_id, "created_at": created_at, "snapshot": snapshot,
                "frequent": frequent, "steps": step(s, "record")}

    def lookup(s):
        account, business = lookup_mock_db(conn, s["registrant_id"], s["frequent"])
        summary = agent.summarize_frequent(s["registrant_id"], s["frequent"]) if llm_on else None
        return {"account": account, "business": business, "lookup_summary": summary,
                "steps": step(s, "lookup")}

    g = StateGraph(VocState)
    for name, fn in [("validate", validate), ("guard", guard), ("policy_check", policy_check),
                     ("rule_match", rule_match),
                     ("agent_judge", agent_judge), ("similar_fallback", similar_fallback),
                     ("guidance", guidance), ("record", record), ("lookup", lookup)]:
        g.add_node(name, fn)
    g.add_edge(START, "validate")
    g.add_conditional_edges("validate", lambda s: "guard" if s["input_validation"]["is_valid"]
                            else END, ["guard", END])
    g.add_edge("guard", "policy_check")
    g.add_conditional_edges("policy_check", lambda s: "record" if s.get("policy") else "rule_match",
                            ["record", "rule_match"])
    g.add_conditional_edges(
        "rule_match",
        lambda s: "record" if s["matched"] else ("agent_judge" if llm_on else "similar_fallback"),
        ["record", "agent_judge", "similar_fallback"])
    g.add_conditional_edges(
        "agent_judge",
        lambda s: "similar_fallback" if s.get("agent_error")
        else ("record" if s["matched"] else "guidance"),
        ["similar_fallback", "record", "guidance"])
    g.add_conditional_edges("similar_fallback",
                            lambda s: "record" if s["matched"] else "guidance",
                            ["record", "guidance"])
    g.add_edge("guidance", "record")
    g.add_conditional_edges("record", lambda s: "lookup" if s["frequent"] else END,
                            ["lookup", END])
    g.add_edge("lookup", END)
    return g.compile()


def run_voc(conn, voc_text, registrant_id, menus=None, use_api=True):
    menus = menus or load_menus()
    llm_on = bool(use_api) and llm.llm_enabled()
    # 그래프 입력은 트레이스(LangSmith)에 그대로 기록되므로, 실행 전에 개인정보를 가린다.
    masked, found = mask_pii((voc_text or "").strip())
    s = build_graph(conn, menus, llm_on).invoke(
        {"voc_text": masked, "registrant_id": registrant_id, "pii_found": found, "steps": []})
    v = s["input_validation"]
    if not v["is_valid"]:
        return {"error": " ".join(v["warnings"]), "warnings": v["warnings"],
                "input_validation": v}
    matched = s.get("matched") or []
    frequent = s.get("frequent") or []
    return {"is_processable": bool(matched), "matched_menus": matched,
            "menu_counts": s["snapshot"], "count_snapshot": s["snapshot"],
            "frequent_menus": frequent, "is_frequent": bool(frequent),
            "guidance_draft": s.get("guidance"), "guidance_source": s.get("guidance_source"),
            "created_at": s["created_at"], "account_info": s.get("account"),
            "business_data": s.get("business") or [], "input_validation": v,
            "voc_id": s["voc_id"], "match_source": s.get("match_source"),
            "similar_voc": s.get("similar"), "judge": s.get("judge"),
            "agent_error": s.get("agent_error"), "lookup_summary": s.get("lookup_summary"),
            "pii_found": s.get("pii_found") or [], "voc_text": s["voc_text"],
            "mode": "llm" if llm_on else "rule", "steps": s["steps"]}
