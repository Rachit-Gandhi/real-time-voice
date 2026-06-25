from typing import TypedDict


class WWTSState(TypedDict, total=False):
    # Identity / session
    thread_id: str
    user_id: str          # WWTS user ID (e.g. "RSMITH")
    user_message: str
    messages: list        # [{"role": "user"|"assistant", "content": str}]
    context: dict         # wwts_session, customer_codes, authorized_functions, user_name, user_type

    # Conversation FSM
    # greeting → intent → collecting_* | confirming_create
    # → executing_list | executing_get | executing_create → done
    stage: str
    intent: str | None    # list_wo | search_wo | get_wo | create_wo | ...
    facts: dict           # canonical facts shared across flows
    active_task: dict     # current task binding, e.g. kind/target_wo/dependencies
    corrections: list     # user corrections applied across facts and legacy fields
    artifacts: dict       # cached results grouped by task/current WO/search

    # Get WO detail
    wo_number: str | None
    wo_detail: dict | None
    wo_remarks: list | None
    wo_parts: list | None
    wo_labor: list | None
    wo_get_focus: str | None   # parts | labor | tech | None
    wo_part_line: int | None
    wo_labor_activities: list | None
    wo_site: dict | None
    wo_part_line_detail: dict | None

    # List / search WOs
    list_customer_code: str | None  # optional filter when confirming per-customer list
    wo_list: list | None
    wo_status: str | None      # "O" = open (default), "C" = closed, "A" = all
    wo_days_back: int | None   # look-back window; closed searches default to 90
    result_limit: int | None   # strict "last N" or "top N" result cap
    search_filters: dict | None  # cust_call, site_id, model, serial, wo_number, ...

    # Create WO
    create_fields: dict
    created_wo_number: str | None
    create_fields_fingerprint: str | None

    # Close / reopen WO
    close_fields: dict | None
    reopen_reason: str | None
    closed_wo_number: str | None
    close_fields_fingerprint: str | None
    reopened_wo_number: str | None
    reopen_reason_fingerprint: str | None
    remark_text: str | None
    remarked_wo_number: str | None
    remark_fingerprint: str | None

    # Support / troubleshooting flow (greet → name → product → issue →
    # generate 2 troubleshoots → walk through → create → two remarks on new WO)
    ts_name: str | None         # caller's name
    ts_product_ref: str | None  # product reference the caller gave
    ts_product_desc: str | None # resolved product description (from lookup)
    ts_device: str | None       # device the caller named (used when lookup is empty)
    ts_issue: str | None        # customer-reported issue, verbatim
    ts_troubleshoots: list | None  # [{title, steps:[...]}, ...] (≤2, ≤10 steps total)
    ts_executed: int | None     # how many troubleshoots we walked the user through
    ts_resolved: bool | None    # did troubleshooting fix it?
    ts_added_remarks: list | None  # exact remark texts the bot logged on the new WO
    pending_troubleshoot: bool  # True between troubleshoot hand-off and create

    # Output
    final_answer: str
    speak: str
    requires_more_info: bool
    session_expired: bool   # True when WWTS rejected the session — UI should prompt re-login
