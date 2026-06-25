"""API execution node — calls WWTS and formats results into natural language."""
import re

from wwts_agent.state import WWTSState
from wwts_agent import api
from wwts_agent.corrections import hydrate_state, sync_legacy_fields


_SESSION_EXPIRED_MSG = (
    "Your WWTS session has expired. Please log out and log back in, "
    "then try again."
)


def _session_expired_state(state: WWTSState) -> WWTSState:
    return {
        **state,
        "stage": "done",
        "session_expired": True,
        "final_answer": _SESSION_EXPIRED_MSG,
        "speak": _SESSION_EXPIRED_MSG,
        "requires_more_info": False,
    }


def _build_ts_issue_remark(state: WWTSState) -> str:
    facts = state.get("facts") or {}
    issue = (
        ((facts.get("issue") or {}).get("value") if isinstance(facts.get("issue"), dict) else facts.get("issue"))
        or state.get("ts_issue")
        or ""
    ).strip() or "(issue not captured)"
    name = (
        ((facts.get("contact_name") or {}).get("value") if isinstance(facts.get("contact_name"), dict) else facts.get("contact_name"))
        or state.get("ts_name")
        or ""
    ).strip()
    who = f" (caller: {name})" if name else ""
    return f"User Comment{who}: {issue}"


def _build_ts_analysis_remark(state: WWTSState, product_desc: str, product_ref: str) -> str:
    facts = state.get("facts") or {}
    issue = (
        ((facts.get("issue") or {}).get("value") if isinstance(facts.get("issue"), dict) else facts.get("issue"))
        or state.get("ts_issue")
        or "n/a"
    )
    device_fact = (
        (facts.get("device") or {}).get("value")
        if isinstance(facts.get("device"), dict)
        else facts.get("device")
    )
    device = product_desc or (device_fact or state.get("ts_device") or "").strip() or product_ref or "the device"
    head = f"AI Comment — analysis for {device}"
    if product_ref and product_desc:
        head += f" (ref {product_ref})"
    head += "."
    parts = [head, f"Reported issue: {str(issue).strip()}."]

    troubleshoots = state.get("ts_troubleshoots") or []
    executed = int(state.get("ts_executed") or 0) or len(troubleshoots)
    done = troubleshoots[:executed]
    if done:
        rendered = []
        for t in done:
            steps = "; ".join(str(s).strip() for s in (t.get("steps") or []))
            rendered.append(f"{t.get('title', 'steps')} — {steps}")
        parts.append("Troubleshooting walked through with customer: " + " | ".join(rendered) + ".")
    if state.get("ts_resolved"):
        parts.append("Outcome: customer confirmed resolved during troubleshooting; WO logged for record.")
    else:
        parts.append("Outcome: not resolved after troubleshooting; on-site service required.")
    text = " ".join(parts)
    return text[:1500]


def _do_troubleshoot_post_create(
    state: WWTSState,
    user_id: str,
    session: int,
    customer_codes,
    wo_num: str,
    create_fields: dict,
) -> WWTSState:
    """After a troubleshoot-driven create succeeds: resolve the product, log the
    customer issue + agent analysis as two remarks, then return the work order."""
    customer = create_fields.get("Customer Code", "")
    product_ref = (create_fields.get("Product Reference") or "").strip()

    # Prefer the description we already resolved during the conversation; only
    # hit the lookup again (now with the authoritative create customer code) if
    # we don't have one yet.
    product_desc = (state.get("ts_product_desc") or "").strip()
    if not product_desc:
        look = api.lookup_product_reference(user_id, session, customer, product_ref)
        if look.get("success") and look.get("product"):
            product_desc = look["product"].get("description", "") or ""

    issue_remark = _build_ts_issue_remark(state)
    analysis_remark = _build_ts_analysis_remark(state, product_desc, product_ref)

    pre = api.get_workorder_full(user_id, session, wo_num, customer_codes=customer_codes)
    detail = pre.get("detail") if pre.get("success") else None

    r1 = api.add_workorder_remark(user_id, session, wo_num, issue_remark, customer_codes, detail=detail)
    r2 = api.add_workorder_remark(user_id, session, wo_num, analysis_remark, customer_codes, detail=detail)
    added = sum(1 for r in (r1, r2) if r.get("success"))

    after = api.get_workorder_full(user_id, session, wo_num, customer_codes=customer_codes)
    detail = after.get("detail") if after.get("success") else (detail or {})
    remarks = after.get("remarks") if after.get("success") else []

    lines = [
        "Work order created and your issue has been logged.",
        f"WO Number: {wo_num}",
        f"Customer:  {customer}",
    ]
    device_label = product_desc or (state.get("ts_device") or "").strip()
    if device_label:
        lines.append(f"Product:   {device_label}" + (f" ({product_ref})" if product_ref else ""))
    elif product_ref:
        lines.append(f"Product:   {product_ref}")
    if detail and detail.get("vstatus"):
        lines.append(f"Status:    {detail['vstatus']}")
    lines.append("")
    if added:
        lines.append(f"Logged {added} remark(s) on this work order:")
        lines.append(f"  1. {issue_remark}")
        lines.append(f"  2. {analysis_remark}")
    else:
        lines.append(
            "Note: the work order was created, but the remarks could not be saved "
            f"({r1.get('error') or r2.get('error') or 'unknown error'})."
        )
    lines.append("")
    lines.append("You can now ask me for this work order's status, remarks, or parts.")
    msg = "\n".join(lines)
    speak = (
        f"Work order {wo_num} created for customer {customer}. "
        f"I logged your issue and my troubleshooting analysis as remarks. "
        "You can ask for its status, remarks, or parts."
    )
    return {
        **state,
        "stage": "done",
        "created_wo_number": wo_num,
        "wo_number": wo_num,
        "wo_detail": detail or {},
        "wo_remarks": remarks or [],
        "remarked_wo_number": wo_num,
        "ts_added_remarks": [issue_remark, analysis_remark] if added else [],
        "pending_troubleshoot": False,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def execute(state: WWTSState) -> WWTSState:
    state = sync_legacy_fields(hydrate_state(dict(state)))
    stage = state.get("stage", "")
    user_id = state.get("user_id", "")
    context = state.get("context") or {}
    session = context.get("wwts_session")
    customer_codes = context.get("customer_codes") or context.get("customer_code") or []

    if not session:
        msg = "No active WWTS session. Please log in first."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    if stage == "executing_list":
        if state.get("intent") == "search_wo":
            return _do_search(state, user_id, session, customer_codes)
        return _do_list(state, user_id, session, customer_codes)
    if stage == "executing_get":
        return _do_get(state, user_id, session, customer_codes)
    if stage == "executing_get_parts":
        return _do_get_parts(state, user_id, session, customer_codes)
    if stage == "executing_get_part_line":
        return _do_get_part_line(state, user_id, session, customer_codes)
    if stage == "executing_get_labor":
        return _do_get_labor(state, user_id, session, customer_codes)
    if stage == "executing_get_labor_activities":
        return _do_get_labor_activities(state, user_id, session, customer_codes)
    if stage == "executing_get_site":
        return _do_get_site(state, user_id, session, customer_codes)
    if stage == "executing_create":
        return _do_create(state, user_id, session, customer_codes, context)
    if stage == "executing_close":
        return _do_close(state, user_id, session, customer_codes, context)
    if stage == "executing_reopen":
        return _do_reopen(state, user_id, session, customer_codes, context)
    if stage == "executing_remark":
        return _do_remark(state, user_id, session, customer_codes, context)

    msg = "Unknown execution stage."
    return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}


def _format_order_list(
    orders: list[dict], status_label: str, days_back: int, display_limit: int = 15
) -> tuple[str, str]:
    if not orders:
        msg = (
            f"No {status_label} work orders found for the requested filters "
            f"(lookback: {days_back} days)."
        )
        return msg, msg

    lines = [f"Found {len(orders)} {status_label} work order(s):\n"]
    for o in orders[:display_limit]:
        wo_num = o.get("ordernum", "")
        cust_call = o.get("custcall", "")
        city = o.get("city", "")
        stop = o.get("laststop", "")
        model = o.get("model", "")
        csr = o.get("csr", "")
        ref = f" | Ref: {cust_call}" if cust_call else ""
        tech = f" | Tech: {csr}" if csr else ""
        lines.append(f"• WO {wo_num}{ref} — {model} — {city} — {stop}{tech}")

    if len(orders) > display_limit:
        lines.append(f"... and {len(orders) - display_limit} more.")

    msg = "\n".join(lines)
    speak = f"Found {len(orders)} {status_label} work orders. " + (
        f"The first one is WO {orders[0].get('ordernum', '')} in {orders[0].get('city', '')}."
        if orders else ""
    )
    return msg, speak


def _do_search(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    search_filters = dict(state.get("search_filters") or {})
    wo_status = search_filters.get("wo_status") or state.get("wo_status") or "A"
    days_back = search_filters.get("days_back") or state.get("wo_days_back") or (
        90 if wo_status != "O" else 30
    )
    search_filters.setdefault("wo_status", wo_status)
    search_filters.setdefault("days_back", days_back)
    result_limit = search_filters.get("result_limit") or state.get("result_limit")
    if isinstance(result_limit, str) and result_limit.isdigit():
        result_limit = int(result_limit)
    if isinstance(result_limit, int) and result_limit > 0:
        search_filters["result_limit"] = result_limit

    result = api.search_workorders(user_id, session, customer_codes, search_filters)
    if not result["success"]:
        if api.is_session_expired_error(result.get("error", "")):
            return _session_expired_state(state)
        msg = result.get("error", "Search could not be completed.")
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    status_label = {"O": "open", "C": "closed", "A": "matching"}.get(wo_status, wo_status)
    all_orders = result["orders"]
    orders = all_orders[:result_limit] if isinstance(result_limit, int) and result_limit > 0 else all_orders
    msg, speak = _format_order_list(orders, status_label, days_back, display_limit=max(result_limit or 15, 1))
    if orders:
        speak = f"Found {len(orders)} matching work orders."
    return {
        **state,
        "stage": "done",
        "wo_list": orders,
        "wo_status": wo_status,
        "wo_days_back": days_back,
        "result_limit": result_limit,
        "search_filters": search_filters,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _do_list(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    wo_status = state.get("wo_status") or "O"
    days_back = state.get("wo_days_back") or (90 if wo_status != "O" else 30)
    codes = customer_codes
    filter_code = (state.get("list_customer_code") or "").strip()
    if filter_code:
        normalized = api._normalize_customer_codes(customer_codes)
        codes = [c for c in normalized if c.upper() == filter_code.upper()]
        if not codes:
            msg = f"Customer code {filter_code} is not in your authorized customer list."
            return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}
    result = api.list_workorders(user_id, session, codes, days_back=days_back, status=wo_status)
    if not result["success"]:
        if api.is_session_expired_error(result.get("error", "")):
            return _session_expired_state(state)
        msg = f"Could not retrieve work orders: {result.get('error', 'unknown error')}."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    _status_label = {"O": "open", "C": "closed", "A": "open or closed"}.get(wo_status, wo_status)

    search_filters = dict(state.get("search_filters") or {})
    result_limit = state.get("result_limit") or search_filters.get("result_limit")
    if isinstance(result_limit, str) and result_limit.isdigit():
        result_limit = int(result_limit)
    all_orders = result["orders"]
    orders = all_orders[:result_limit] if isinstance(result_limit, int) and result_limit > 0 else all_orders
    msg, speak = _format_order_list(orders, _status_label, days_back, display_limit=max(result_limit or 15, 1))
    return {
        **state,
        "stage": "done",
        "wo_list": orders,
        "result_limit": result_limit,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _format_parts_section(parts: list[dict]) -> list[str]:
    lines = [f"\nParts ({len(parts)} line(s)):"]
    for p in parts[:10]:
        part_no = p.get("partno") or p.get("PartNo") or p.get("partnum") or p.get("PartNum") or ""
        desc = p.get("partdesc") or p.get("description") or p.get("descr") or p.get("Descr") or ""
        status = p.get("partstatus") or p.get("status") or p.get("linestatus") or p.get("LineStatus") or ""
        lines.append(f"  • {part_no} — {desc} — {status}".rstrip(" —"))
    if len(parts) > 10:
        lines.append(f"  ... and {len(parts) - 10} more part lines.")
    return lines


def _format_labor_section(labor: list[dict]) -> list[str]:
    lines = [f"\nLabor ({len(labor)} item(s)):"]
    for item in labor[:10]:
        csr = item.get("csr") or item.get("CSR") or ""
        name = item.get("csrname") or item.get("name") or ""
        status = item.get("status") or item.get("laborstatus") or ""
        lines.append(f"  • {csr} {name} — {status}".strip())
    if len(labor) > 10:
        lines.append(f"  ... and {len(labor) - 10} more labor entries.")
    return lines


def _build_get_speak(
    d: dict,
    parts: list[dict],
    labor: list[dict],
    wo_number: str,
    focus: str | None,
) -> str:
    order = d.get("ordernum", wo_number)
    status = d.get("vstatus", "unknown")
    last_stop = d.get("laststop", "unknown")
    csr = d.get("CSR", "") or "not assigned"
    eta = d.get("eta", "")
    part_count = len(parts)
    labor_count = len(labor)

    if focus == "parts":
        if part_count:
            return (
                f"Work order {order} has {part_count} part line(s). "
                f"Status is {status}."
            )
        return f"Work order {order} has no parts on file. Status is {status}."

    if focus in ("labor", "tech"):
        tech_line = csr
        if labor_count:
            first = labor[0]
            tech_line = first.get("csr") or first.get("CSR") or csr
        return (
            f"Work order {order} technician is {tech_line}. "
            f"There are {labor_count} labor item(s). Last stop is {last_stop}."
        )

    speak = (
        f"Work order {order} status is {status}, last stop {last_stop}. "
        f"Technician {csr}. "
    )
    if part_count:
        speak += f"{part_count} part line(s). "
    if labor_count:
        speak += f"{labor_count} labor item(s). "
    if eta:
        speak += f"ETA {eta}."
    return speak.strip()


def _build_remarks_speak(d: dict, remarks: list[dict], wo_number: str) -> str:
    order = d.get("ordernum", wo_number)
    if not remarks:
        return f"Work order {order} has no remarks on file."
    latest = remarks[-1]
    author = latest.get("author", "")
    text = (latest.get("remdata") or "").strip()
    count = len(remarks)
    speak = f"Work order {order} has {count} remark{'s' if count != 1 else ''}. "
    if text:
        speak += f"The latest, from {author or 'a user'}: {text}"
    return speak.strip()


_BOT_REMARK_PREFIXES = ("User Comment", "AI Comment")


def _split_remarks(remarks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (real_remarks, bot_remarks). ``real`` drops blank/duplicate entries
    (GetCallRemarks returns the full activity log, most of it empty system rows);
    ``bot`` are the comments this assistant logged (matched by their prefixes)."""
    real: list[dict] = []
    seen: set = set()
    for r in remarks or []:
        text = (r.get("remdata") or "").strip()
        if not text:
            continue
        author = str(r.get("author", "") or "").strip()
        key = (author, text)
        if key in seen:
            continue
        seen.add(key)
        real.append({
            "author": author,
            "text": text,
            "dt": str(r.get("entdatetime", "") or "").strip(),
        })
    bot = [r for r in real if r["text"].startswith(_BOT_REMARK_PREFIXES)]
    return real, bot


def _remarks_view(order: str, remarks: list[dict], want_all: bool) -> tuple[str, str]:
    """Build (answer, speak) for a remarks read — surfaces the bot-logged comments
    first and lists the real remarks, ignoring the empty system activity rows."""
    real, bot = _split_remarks(remarks)
    if not real:
        msg = f"Work order {order} has no remarks on file."
        return msg, msg

    lines = [f"Remarks for WO {order} — {len(real)} remark(s):"]
    for i, r in enumerate(real[:20], start=1):
        meta = " / ".join(x for x in (r["dt"], r["author"]) if x)
        lines.append(f"  {i}. {r['text']}" + (f"  [{meta}]" if meta else ""))
    if len(real) > 20:
        lines.append(f"  ... and {len(real) - 20} more.")
    msg = "\n".join(lines)

    if want_all:
        speak = f"Work order {order} has {len(real)} remark(s). " + " ".join(
            f"{i}: {r['text']}." for i, r in enumerate(real[:6], start=1)
        )
    elif bot:
        body = "; ".join(b["text"] for b in bot)
        extra = len(real) - len(bot)
        speak = (
            f"Work order {order} has {len(bot)} logged remark"
            f"{'s' if len(bot) != 1 else ''}: {body}."
        )
        if extra > 0:
            speak += f" There are also {extra} earlier activity entr{'y' if extra == 1 else 'ies'}."
    else:
        latest = real[-1]
        speak = (
            f"Work order {order} has {len(real)} remark{'s' if len(real) != 1 else ''}. "
            f"Most recent, from {latest['author'] or 'a user'}: {latest['text']}"
        )
    return msg, speak.strip()


def _do_get(
    state: WWTSState,
    user_id: str,
    session: int,
    customer_codes,
) -> WWTSState:
    wo_number = state.get("wo_number", "")
    result = api.get_workorder_full(user_id, session, wo_number, customer_codes=customer_codes)

    if not result["success"]:
        error_detail = result.get("error", "")
        if api.is_session_expired_error(error_detail):
            return _session_expired_state(state)
        if error_detail:
            msg = f"Work order {wo_number} could not be retrieved: {error_detail}."
        else:
            msg = f"Work order {wo_number} was not found."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    d = result["detail"]
    remarks = result["remarks"]
    parts = result.get("parts") or []
    labor = result.get("labor") or []
    focus = state.get("wo_get_focus")

    lines = [
        f"Work Order: {d.get('ordernum', wo_number)}",
        f"Status:     {d.get('vstatus', 'Unknown')}",
        f"Customer:   {d.get('custname', '')}",
        f"End User:   {d.get('endcust', '')}",
        f"Model:      {d.get('equip_model', '')}  Serial: {d.get('equip_serial', '')}",
        f"Location:   {d.get('city', '')}, {d.get('state', '')}  {d.get('zip', '')}",
        f"Contact:    {d.get('contactname', '')}  {d.get('contactphone', '')}",
        f"Opened:     {d.get('opened', '')}",
        f"Last Stop:  {d.get('laststop', '')}",
        f"Tech (CSR): {d.get('CSR', '')}",
    ]
    if d.get("eta"):
        lines.append(f"ETA:        {d['eta']}")
    if d.get("sla"):
        lines.append(f"SLA:        {d['sla']}")

    if parts:
        lines.extend(_format_parts_section(parts))
    else:
        lines.append("\nNo parts on file.")

    if labor:
        lines.extend(_format_labor_section(labor))
    else:
        lines.append("\nNo labor items on file.")

    if remarks:
        lines.append(f"\nActivity History ({len(remarks)} entries):")
        for r in remarks[-10:]:
            dt = r.get("entdatetime", "")
            author = r.get("author", "")
            text = (r.get("remdata") or "").strip()
            lines.append(f"  [{dt}] {author}: {text}")
    else:
        lines.append("\nNo remarks on file.")

    order = d.get("ordernum", wo_number)
    if focus == "remarks":
        want_all = bool(re.search(r"\b(all|list|every|full)\b", (state.get("user_message") or "").lower()))
        msg, speak = _remarks_view(order, remarks, want_all)
    else:
        msg = "\n".join(lines)
        speak = _build_get_speak(d, parts, labor, wo_number, focus)

    return {
        **state,
        "stage": "done",
        "wo_detail": d,
        "wo_remarks": remarks,
        "wo_parts": parts,
        "wo_labor": labor,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _scope_error_state(state: WWTSState, wo_number: str, error: str) -> WWTSState:
    if api.is_session_expired_error(error):
        return _session_expired_state(state)
    msg = f"Work order {wo_number} could not be retrieved: {error}."
    return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}


def _do_get_parts(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    wo_number = state.get("wo_number", "")
    result = api.get_workorder_parts(user_id, session, wo_number, customer_codes)
    if not result["success"]:
        return _scope_error_state(state, wo_number, result.get("error", ""))

    parts = result["parts"]
    order = (result.get("detail") or {}).get("ordernum", wo_number)
    if not parts:
        msg = f"No parts on file for work order {order}."
        speak = f"Work order {order} has no parts on file."
        return {
            **state,
            "stage": "done",
            "wo_parts": [],
            "final_answer": msg,
            "speak": speak,
            "requires_more_info": False,
        }

    lines = [f"Parts for WO {order} ({len(parts)} line(s)):\n"]
    for p in parts[:15]:
        part_no = p.get("partno") or p.get("PartNo") or p.get("partnum") or p.get("PartNum") or ""
        desc = p.get("partdesc") or p.get("description") or p.get("descr") or p.get("Descr") or ""
        status = p.get("partstatus") or p.get("status") or p.get("linestatus") or p.get("LineStatus") or ""
        line = p.get("linenum") or p.get("line") or p.get("LineNum") or ""
        lines.append(f"  • Line {line}: {part_no} — {desc} — {status}".rstrip(" —"))
    if len(parts) > 15:
        lines.append(f"... and {len(parts) - 15} more.")
    msg = "\n".join(lines)
    speak = f"Work order {order} has {len(parts)} part line(s)."
    return {
        **state,
        "stage": "done",
        "wo_parts": parts,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _do_get_part_line(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    wo_number = state.get("wo_number", "")
    line_no = state.get("wo_part_line")
    if not line_no:
        msg = "Which part line number should I look up?"
        return {
            **state,
            "stage": "collecting_wo_part_line",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    result = api.get_workorder_part_line(
        user_id, session, wo_number, int(line_no), customer_codes
    )
    if not result["success"]:
        return _scope_error_state(state, wo_number, result.get("error", ""))

    p = result.get("part_line") or {}
    if not p:
        msg = f"No part line {line_no} found on work order {wo_number}."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    part_no = p.get("partno") or p.get("PartNo") or ""
    desc = p.get("partdesc") or p.get("description") or ""
    status = p.get("partstatus") or p.get("status") or ""
    msg = (
        f"Part line {line_no} on WO {wo_number}:\n"
        f"  Part:   {part_no}\n"
        f"  Desc:   {desc}\n"
        f"  Status: {status}"
    )
    speak = f"Part line {line_no} on work order {wo_number} is {part_no}, status {status}."
    return {
        **state,
        "stage": "done",
        "wo_part_line_detail": p,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _do_get_labor(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    wo_number = state.get("wo_number", "")
    result = api.get_workorder_labor(user_id, session, wo_number, customer_codes)
    if not result["success"]:
        return _scope_error_state(state, wo_number, result.get("error", ""))

    labor = result["labor"]
    order = (result.get("detail") or {}).get("ordernum", wo_number)
    csr = (result.get("detail") or {}).get("CSR", "")
    if not labor:
        msg = f"No labor items on file for work order {order}."
        speak = f"Work order {order} has no labor items. Assigned CSR is {csr or 'unknown'}."
        return {
            **state,
            "stage": "done",
            "wo_labor": [],
            "final_answer": msg,
            "speak": speak,
            "requires_more_info": False,
        }

    lines = [f"Labor for WO {order} ({len(labor)} item(s)):\n"]
    for item in labor[:15]:
        tech = item.get("csr") or item.get("CSR") or ""
        name = item.get("csrname") or item.get("name") or ""
        status = item.get("status") or item.get("laborstatus") or ""
        lines.append(f"  • {tech} {name} — {status}".strip())
    if len(labor) > 15:
        lines.append(f"... and {len(labor) - 15} more.")
    msg = "\n".join(lines)
    speak = f"Work order {order} has {len(labor)} labor item(s). Primary CSR is {csr or 'unknown'}."
    return {
        **state,
        "stage": "done",
        "wo_labor": labor,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _do_get_labor_activities(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    wo_number = state.get("wo_number", "")
    result = api.get_workorder_labor_activities(user_id, session, wo_number, customer_codes)
    if not result["success"]:
        return _scope_error_state(state, wo_number, result.get("error", ""))

    activities = result["labor_activities"]
    order = (result.get("detail") or {}).get("ordernum", wo_number)
    if not activities:
        msg = f"No labor activities on file for work order {order}."
        speak = f"Work order {order} has no labor activities on file."
        return {
            **state,
            "stage": "done",
            "wo_labor_activities": [],
            "final_answer": msg,
            "speak": speak,
            "requires_more_info": False,
        }

    lines = [f"Labor activities for WO {order} ({len(activities)}):\n"]
    for act in activities[:15]:
        line = act.get("linenum") or act.get("line") or act.get("LineNo") or ""
        desc = act.get("activity") or act.get("description") or act.get("actdesc") or ""
        dt = act.get("activitydate") or act.get("date") or ""
        lines.append(f"  • Line {line}: {desc} ({dt})".rstrip())
    if len(activities) > 15:
        lines.append(f"... and {len(activities) - 15} more.")
    msg = "\n".join(lines)
    speak = f"Work order {order} has {len(activities)} labor activit{'y' if len(activities) == 1 else 'ies'}."
    return {
        **state,
        "stage": "done",
        "wo_labor_activities": activities,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _user_wants_address(user_message: str) -> bool:
    lower = (user_message or "").lower()
    return any(k in lower for k in ("address", "street", "full location", "where is"))


def _do_get_site(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    wo_number = state.get("wo_number", "")
    user_message = state.get("user_message", "")
    result = api.get_workorder_site(user_id, session, wo_number, customer_codes)
    if not result["success"]:
        return _scope_error_state(state, wo_number, result.get("error", ""))

    site = result.get("site") or {}
    order = (result.get("detail") or {}).get("ordernum", wo_number)
    city = site.get("City", "")
    state_abbr = site.get("State", "")
    zip_code = site.get("Zip", "")
    end_cust = site.get("EndCust", "")
    site_id = site.get("SiteID", "")

    lines = [
        f"Site for WO {order}:",
        f"  Site ID:  {site_id}",
        f"  End user: {end_cust}",
        f"  City:     {city}, {state_abbr}  {zip_code}",
    ]
    if _user_wants_address(user_message):
        if site.get("StreetAddress"):
            lines.append(f"  Street:   {site['StreetAddress']}")
        if site.get("AddtlAddr"):
            lines.append(f"  Addr 2:   {site['AddtlAddr']}")
        if site.get("SiteContact"):
            lines.append(f"  Contact:  {site['SiteContact']}")
        if site.get("SitePhone"):
            lines.append(f"  Phone:    {site['SitePhone']}")

    msg = "\n".join(lines)
    speak = f"Work order {order} site is in {city}, {state_abbr}."
    return {
        **state,
        "stage": "done",
        "wo_site": site,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _address_error_recovery(create_fields: dict, result_msg: str) -> tuple[dict, str]:
    """Decide how to recover from a WWTS address-validation failure.

    Returns (possibly-cleaned create_fields, message). Never re-asks for the
    exact same fields that just failed — escalates to a street address, then to
    a recheck/Site-ID prompt, so the create flow can't loop.
    """
    reason = (result_msg or "").strip().rstrip(".")
    reason_tail = f" (WWTS said: {reason})" if reason else ""
    bad_site = create_fields.get("Site ID", "")
    has_location = bool(
        create_fields.get("Customer City")
        and create_fields.get("Customer State")
        and create_fields.get("Customer Postal Code")
    )
    has_street = bool(create_fields.get("Customer Address"))

    if bad_site:
        cleaned = {k: v for k, v in create_fields.items() if k != "Site ID"}
        return cleaned, (
            f"The Site ID '{bad_site}' wasn't found in the system{reason_tail}. "
            "Could you give me the street address (with city, state, and ZIP), "
            "or double-check the Site ID?"
        )

    if has_location and not has_street:
        # City/state/ZIP were rejected. Re-asking for the same three fields just
        # loops — escalate to the street address the validator needs to geocode.
        return create_fields, (
            "I couldn't validate that location from just the city, state, and ZIP"
            f"{reason_tail}. What's the street address for the site?"
        )

    # Street already supplied (or no location at all) and it still failed —
    # surface the real reason and offer the Site ID path instead of repeating.
    return create_fields, (
        f"That address still didn't validate{reason_tail}. "
        "Please double-check the street, city, state, and ZIP — "
        "or give me a Site ID to use instead."
    )


def _do_create(
    state: WWTSState,
    user_id: str,
    session: int,
    customer_codes,
    context: dict,
) -> WWTSState:
    thread_id = state.get("thread_id", "")
    create_fields = api._normalize_fields(state.get("create_fields") or {})
    fingerprint = api.create_fields_fingerprint(create_fields)

    authorized = context.get("authorized_functions") or []
    auth_ok = api.is_authorized_for_create(authorized)
    if not auth_ok:
        msg = (
            "You are not authorized to create work orders in WWTS. "
            "Please contact your administrator if you need access."
        )
        api.log_wwts_action(
            "create_wo_denied_auth",
            user_id=user_id,
            thread_id=thread_id,
            customer_code=create_fields.get("Customer Code", ""),
            authorized_count=len(authorized),
            context_had_auth=bool(context.get("authorized_functions")),
            reason=(
                "no authorized_functions in context/session enrichment"
                if not authorized
                else "no create/open permission found in authorized_functions"
            ),
        )
        return {
            **state,
            "stage": "done",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": False,
        }

    try:
        api.assert_create_customer_in_scope(
            create_fields.get("Customer Code", ""), customer_codes
        )
    except ValueError as exc:
        msg = str(exc)
        return {
            **state,
            "stage": "collecting_create",
            "create_fields": create_fields,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    prior_wo = state.get("created_wo_number")
    prior_fp = state.get("create_fields_fingerprint")
    if prior_wo and prior_fp and prior_fp == fingerprint:
        msg = (
            f"Work order {prior_wo} was already created in this conversation with the same details. "
            "Say if you want to create another work order with different information."
        )
        return {
            **state,
            "stage": "intent",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    has_site = bool(create_fields.get("Site ID"))
    has_partial_location = bool(
        create_fields.get("Customer City") or create_fields.get("Customer Postal Code")
    )
    if not has_site and has_partial_location and not create_fields.get("Customer State"):
        msg = (
            "Please provide the customer state as well so I can create the work order "
            "with the city, state, and postal code."
        )
        return {
            **state,
            "stage": "collecting_create",
            "create_fields": create_fields,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    api.log_wwts_action(
        "create_wo_attempt",
        user_id=user_id,
        thread_id=thread_id,
        customer_code=create_fields.get("Customer Code", ""),
        field_hash=fingerprint,
    )

    result = api.create_workorder(user_id, session, create_fields)

    api.log_wwts_action(
        "create_wo_result",
        user_id=user_id,
        thread_id=thread_id,
        customer_code=create_fields.get("Customer Code", ""),
        RC=result.get("RC"),
        OrderNum=result.get("OrderNum", ""),
        success=result.get("success"),
    )

    if result["success"]:
        wo_num = result.get("OrderNum", "")
        customer = create_fields.get("Customer Code", "")
        # Troubleshoot-driven create: log issue + analysis as two remarks and
        # return the work order to the user.
        if state.get("pending_troubleshoot") and wo_num:
            ts_state = {**state, "create_fields_fingerprint": fingerprint}
            return _do_troubleshoot_post_create(
                ts_state, user_id, session, customer_codes, wo_num, create_fields
            )
        wo_display = wo_num or "(check WWTS portal)"
        msg = (
            f"Work order created successfully!\n"
            f"WO Number:  {wo_display}\n"
            f"Customer:   {customer}"
        )
        speak = (
            f"Work order {wo_num} has been created for customer {customer}."
            if wo_num else
            f"Work order submitted for customer {customer}. Please check the WWTS portal for the WO number."
        )
        return {
            **state,
            "stage": "done",
            "created_wo_number": wo_num,
            "wo_number": wo_num or state.get("wo_number"),
            "create_fields_fingerprint": fingerprint,
            "final_answer": msg,
            "speak": speak,
            "requires_more_info": False,
        }

    if result.get("session_expired") or api.is_session_expired_error(result.get("ResultMsg", "")):
        api.log_wwts_action(
            "create_wo_session_expired",
            user_id=user_id,
            thread_id=thread_id,
            customer_code=create_fields.get("Customer Code", ""),
        )
        return _session_expired_state(state)

    if api._is_address_error(result.get("ResultMsg", "")):
        cleaned, msg = _address_error_recovery(create_fields, result.get("ResultMsg", ""))
        return {
            **state,
            "stage": "collecting_create",
            "intent": "create_wo",
            "create_fields": cleaned,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    msg = f"Failed to create work order: {result.get('ResultMsg', 'unknown error')}."
    return {
        **state,
        "stage": "done",
        "final_answer": msg,
        "speak": msg,
        "requires_more_info": False,
    }


def _do_close(
    state: WWTSState,
    user_id: str,
    session: int,
    customer_codes,
    context: dict,
) -> WWTSState:
    thread_id = state.get("thread_id", "")
    wo_number = (state.get("wo_number") or "").strip()
    close_fields = api._normalize_close_fields(state.get("close_fields") or {})
    fingerprint = api.close_fields_fingerprint(wo_number, close_fields)
    detail = state.get("wo_detail")

    authorized = context.get("authorized_functions") or []
    if not api.is_authorized_for_close(authorized):
        msg = (
            "You are not authorized to close work orders in WWTS. "
            "Please contact your administrator if you need access."
        )
        api.log_wwts_action(
            "close_wo_denied_auth",
            user_id=user_id,
            thread_id=thread_id,
            wo_number=wo_number,
        )
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    prior_wo = state.get("closed_wo_number")
    prior_fp = state.get("close_fields_fingerprint")
    if prior_wo and prior_fp and prior_wo == wo_number and prior_fp == fingerprint:
        msg = (
            f"Work order {wo_number} was already closed in this conversation with the same reason. "
            "Say if you need to close a different work order."
        )
        return {
            **state,
            "stage": "intent",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    missing = api.missing_close_fields(close_fields)
    if missing:
        msg = "I still need: " + ", ".join(missing) + "."
        return {
            **state,
            "stage": "collecting_close_reason",
            "close_fields": close_fields,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    api.log_wwts_action(
        "close_wo_attempt",
        user_id=user_id,
        thread_id=thread_id,
        wo_number=wo_number,
        field_hash=fingerprint,
    )

    result = api.close_workorder(
        user_id,
        session,
        wo_number,
        close_fields,
        customer_codes,
        detail=detail if isinstance(detail, dict) else None,
    )

    api.log_wwts_action(
        "close_wo_result",
        user_id=user_id,
        thread_id=thread_id,
        wo_number=wo_number,
        RC=result.get("RC"),
        success=result.get("success"),
    )

    if result.get("already_closed"):
        msg = result.get("error") or "Work order is already closed."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    if result["success"]:
        msg = f"Work order {wo_number} has been closed successfully."
        return {
            **state,
            "stage": "done",
            "closed_wo_number": wo_number,
            "close_fields_fingerprint": fingerprint,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": False,
        }

    msg = f"Failed to close work order: {result.get('error') or result.get('ResultMsg', 'unknown error')}."
    return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}


def _do_reopen(
    state: WWTSState,
    user_id: str,
    session: int,
    customer_codes,
    context: dict,
) -> WWTSState:
    thread_id = state.get("thread_id", "")
    wo_number = (state.get("wo_number") or "").strip()
    reopen_reason = (state.get("reopen_reason") or "").strip()
    fingerprint = api.reopen_reason_fingerprint(wo_number, reopen_reason)
    detail = state.get("wo_detail")

    authorized = context.get("authorized_functions") or []
    if not api.is_authorized_for_reopen(authorized):
        msg = (
            "You are not authorized to reopen work orders in WWTS. "
            "Please contact your administrator if you need access."
        )
        api.log_wwts_action(
            "reopen_wo_denied_auth",
            user_id=user_id,
            thread_id=thread_id,
            wo_number=wo_number,
        )
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    prior_wo = state.get("reopened_wo_number")
    prior_fp = state.get("reopen_reason_fingerprint")
    if prior_wo and prior_fp and prior_wo == wo_number and prior_fp == fingerprint:
        msg = (
            f"Work order {wo_number} was already reopened in this conversation with the same reason. "
            "Say if you need to reopen a different work order."
        )
        return {
            **state,
            "stage": "intent",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    if len(reopen_reason) < api._MIN_LIFECYCLE_REASON_LEN:
        msg = "Please provide a reopen reason (at least 5 characters)."
        return {
            **state,
            "stage": "collecting_reopen_reason",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    api.log_wwts_action(
        "reopen_wo_attempt",
        user_id=user_id,
        thread_id=thread_id,
        wo_number=wo_number,
        field_hash=fingerprint,
    )

    result = api.reopen_workorder(
        user_id,
        session,
        wo_number,
        reopen_reason,
        customer_codes,
        detail=detail if isinstance(detail, dict) else None,
    )

    api.log_wwts_action(
        "reopen_wo_result",
        user_id=user_id,
        thread_id=thread_id,
        wo_number=wo_number,
        RC=result.get("RC"),
        success=result.get("success"),
    )

    if result.get("already_open"):
        msg = result.get("error") or "Work order is already open."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    if result["success"]:
        msg = f"Work order {wo_number} has been reopened successfully."
        return {
            **state,
            "stage": "done",
            "reopened_wo_number": wo_number,
            "reopen_reason_fingerprint": fingerprint,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": False,
        }

    msg = f"Failed to reopen work order: {result.get('error') or result.get('ResultMsg', 'unknown error')}."
    return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}


def _do_remark(
    state: WWTSState,
    user_id: str,
    session: int,
    customer_codes,
    context: dict,
) -> WWTSState:
    thread_id = state.get("thread_id", "")
    wo_number = (state.get("wo_number") or "").strip()
    remark_text = (state.get("remark_text") or "").strip()
    rem_type = context.get("remark_type") or ""
    fingerprint = api.remark_fingerprint(wo_number, remark_text, rem_type or "GEN")
    detail = state.get("wo_detail")

    authorized = context.get("authorized_functions") or []
    if not api.is_authorized_for_remark(authorized):
        msg = (
            "You are not authorized to add work order remarks in WWTS. "
            "Please contact your administrator if you need access."
        )
        api.log_wwts_action(
            "remark_wo_denied_auth",
            user_id=user_id,
            thread_id=thread_id,
            wo_number=wo_number,
        )
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    prior_wo = state.get("remarked_wo_number")
    prior_fp = state.get("remark_fingerprint")
    if prior_wo and prior_fp and prior_wo == wo_number and prior_fp == fingerprint:
        msg = (
            f"A matching remark was already added to work order {wo_number} in this conversation. "
            "Say if you want to add a different remark."
        )
        return {
            **state,
            "stage": "intent",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    if len(remark_text) < api._MIN_LIFECYCLE_REASON_LEN:
        msg = "Please provide a remark with at least 5 characters."
        return {
            **state,
            "stage": "collecting_remark_text",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    api.log_wwts_action(
        "remark_wo_attempt",
        user_id=user_id,
        thread_id=thread_id,
        wo_number=wo_number,
        field_hash=fingerprint,
    )

    result = api.add_workorder_remark(
        user_id,
        session,
        wo_number,
        remark_text,
        customer_codes,
        detail=detail if isinstance(detail, dict) else None,
        rem_type=rem_type or None,
    )

    api.log_wwts_action(
        "remark_wo_result",
        user_id=user_id,
        thread_id=thread_id,
        wo_number=wo_number,
        RC=result.get("RC"),
        success=result.get("success"),
    )

    if result["success"]:
        msg = f"Remark added to work order {wo_number}."
        return {
            **state,
            "stage": "done",
            "remarked_wo_number": wo_number,
            "remark_fingerprint": fingerprint,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": False,
        }

    msg = f"Failed to add remark: {result.get('error') or result.get('ResultMsg', 'unknown error')}."
    return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}
